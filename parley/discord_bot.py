"""The Discord table: posts queued messages, records what humans say, gets rulers to answer.

One bot speaks for every LLM ruler ("**Doge Enrico (Venice):** ..."). #lobby is public;
each pair of factions has a private thread "<a> ↔ <b>" under #lobby, with that pair's
humans added. The core (pump_outbox, handle_incoming) is Discord-free and tested;
DiscordTable and run_bot are the thin discord.py layer, checked live.
"""

import asyncio
import fcntl
import logging
import os
from pathlib import Path
from typing import Protocol

from parley.chat import Responder
from parley.config import GameConfig, channel_slug  # noqa: F401  (channel_slug re-exported)
from parley.seats import make_seat
from parley.store import Store

log = logging.getLogger("parley.discord")
DISCORD_LIMIT = 2000
PUMP_SECONDS = 2.0


class Table(Protocol):
    async def send(self, channel: str, text: str) -> None: ...
    async def ensure_pair(self, a: str, b: str, humans: list[str]) -> str | None:
        """Make sure the private thread exists; return a clickable mention of it."""
        ...
    async def ensure_adviser(self, faction: str, username: str | None) -> str | None:
        """Make sure the ruler's thread with its adviser exists; return a mention of it."""
        ...


def format_line(name: str, faction_display: str, text: str) -> str:
    return f"**{name} ({faction_display}):** {text}"[:DISCORD_LIMIT]


MAX_ATTEMPTS = 5  # a row that fails this many pumps in a row is set aside, not retried forever


def acquire_bot_lock(turn_root: Path):
    """One bot per turn root: a second copy would post everything twice."""
    turn_root.mkdir(parents=True, exist_ok=True)
    f = open(turn_root / ".discord-bot.lock", "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise RuntimeError(f"a Parley bot is already running on {turn_root}")
    return f


async def pump_outbox(store: Store, table: Table, game_id: str, names: dict[str, str],
                      humans: dict[str, str], attempts: dict[int, int] | None = None,
                      advisers: dict[str, str] | None = None) -> int:
    """Post unposted rows in order; returns how many were posted.

    Stops at the first failure so order is kept. A row that has failed MAX_ATTEMPTS pumps is
    set aside (marked failed and logged) so it can't block everything after it forever.
    """
    attempts = {} if attempts is None else attempts
    posted = 0
    for m in store.unposted(game_id):
        try:
            if m.channel.startswith("pair:"):
                a, b = m.channel.removeprefix("pair:").split("|")
                await table.ensure_pair(a, b, [humans[f] for f in (a, b) if f in humans])
            elif m.channel.startswith("adviser:"):
                faction = m.channel.removeprefix("adviser:")
                await table.ensure_adviser(faction, (advisers or {}).get(faction))
            if m.sender == "parley":  # system notices (turn cues, transfers), posted plain
                await table.send(m.channel, m.text[:DISCORD_LIMIT])
            else:
                await table.send(m.channel, format_line(names.get(m.sender, m.sender),
                                                        m.sender.replace("_", " ").title(), m.text))
        except Exception as e:  # network, permissions: retry on the next pump
            attempts[m.id] = attempts.get(m.id, 0) + 1
            if attempts[m.id] >= MAX_ATTEMPTS:
                log.error("outbox row %d failed %d times, set aside: %s", m.id, attempts[m.id], e)
                store.mark_failed(m.id)
                continue
            log.warning("posting outbox row %d failed: %s", m.id, e)
            break
        store.mark_posted(m.id)
        posted += 1
    return posted


async def handle_incoming(responder, humans: dict[str, str], author: str, is_bot: bool,
                          channel: str | None, text: str, advisers: dict[str, str] | None = None) -> None:
    """A Discord message from `author` in store channel `channel` (None if not ours)."""
    if is_bot or channel is None:
        return
    if channel.startswith("adviser:"):  # only the ruler's own adviser speaks there
        faction = channel.removeprefix("adviser:")
        if (advisers or {}).get(faction) == author:
            await responder.on_incoming(channel, f"adviser:{faction}", text[:DISCORD_LIMIT])
        return
    faction = next((f for f, user in humans.items() if user == author), None)
    if faction is None:
        return
    await responder.on_incoming(channel, f"human:{faction}", text[:DISCORD_LIMIT])


async def private_command(table: Table, humans: dict[str, str], seats: set[str], author: str,
                          text: str) -> str | None:
    """'!private <faction>' from a human: open (or reuse) their private thread with that ruler.

    Returns a reply for the lobby, or None if the message isn't this command from a known human.
    """
    parts = text.strip().split()
    if len(parts) != 2 or parts[0].lower() != "!private":
        return None
    me = next((f for f, user in humans.items() if user == author), None)
    if me is None:
        return None
    other = parts[1].lower()
    if other not in seats or other == me:
        return f"unknown faction '{parts[1]}'. Rulers here: {', '.join(sorted(seats))}"
    a, b = sorted((me, other))
    link = await table.ensure_pair(a, b, [humans[f] for f in (a, b) if f in humans])
    return f"Private thread **{a} ↔ {b}** is open: {link or ''} (only the two of you read it)."


async def adviser_command(table: Table, advisers: dict[str, str], author: str, text: str) -> str | None:
    """'!adviser' from an adviser: open (or reuse) their thread with each ruler they advise."""
    if text.strip().lower() != "!adviser":
        return None
    mine = sorted(f for f, user in advisers.items() if user == author)
    if not mine:
        return None
    links = [f"**adviser ↔ {f}**: {await table.ensure_adviser(f, author) or ''}" for f in mine]
    return "Your counsel is welcome (only you and the ruler read these):\n" + "\n".join(links)


class DiscordTable:
    """Table over discord.py: #lobby plus one private thread per faction pair."""

    def __init__(self, client, config: GameConfig):
        self.client, self.config = client, config
        self.lobby = self.table = None
        self.threads: dict[str, object] = {}  # store channel -> discord thread
        self.thread_channels: dict[int, str] = {}  # discord thread id -> store channel

    async def connect(self) -> None:
        import discord
        guild = discord.utils.get(self.client.guilds, name=self.config.discord.guild)
        if guild is None:
            raise RuntimeError(f"bot is not in a server named {self.config.discord.guild!r}")
        self.guild = guild
        self.lobby = discord.utils.get(guild.text_channels, name=self.config.discord.lobby)
        if self.lobby is None:
            raise RuntimeError(f"no #{self.config.discord.lobby} channel in {guild.name}")
        # this game's own channel for turn notices: find it, create it (needs Manage Channels),
        # or fall back to the lobby
        name = self.config.discord.game_channel
        self.chronicle = discord.utils.get(guild.text_channels, name=name)
        if self.chronicle is None:
            try:
                self.chronicle = await guild.create_text_channel(
                    name, category=self.lobby.category, topic=f"Turn notices for game {self.config.game_id}")
                log.info("created #%s for this game", name)
            except discord.Forbidden:
                log.warning("can't create #%s (bot lacks Manage Channels); turn notices go to #%s",
                            name, self.lobby.name)
                self.chronicle = self.lobby
        # The game's channel is its public table: public talk is read from it and from #lobby,
        # posted to it, and private threads open under it. Only threads under this game's own
        # channel are adopted: thread names carry no game id, so threads under #lobby (or another
        # game's channel) could belong to a different game and its players.
        self.table = self.chronicle
        if self.table.id != self.lobby.id:
            for t in list(self.table.threads) + [t async for t in self.table.archived_threads(private=True)]:
                if t.name.startswith("adviser ↔ "):
                    self._remember(f"adviser:{t.name.removeprefix('adviser ↔ ')}", t)
                elif " ↔ " in t.name:
                    a, b = t.name.split(" ↔ ")
                    self._remember(f"pair:{a}|{b}", t)

    def _remember(self, channel: str, thread) -> None:
        self.threads[channel] = thread
        self.thread_channels[thread.id] = channel

    def channel_for(self, message) -> str | None:
        if message.channel.id in {c.id for c in (self.lobby, self.table) if c is not None}:
            return "lobby"
        return self.thread_channels.get(message.channel.id)

    async def ensure_pair(self, a: str, b: str, humans: list[str]) -> str | None:
        import discord
        channel = f"pair:{a}|{b}"
        if channel in self.threads:
            return self.threads[channel].mention
        thread = await self.table.create_thread(
            name=f"{a} ↔ {b}", type=discord.ChannelType.private_thread, invitable=False)
        for username in humans:
            member = discord.utils.get(self.guild.members, name=username) \
                or await self._fetch_member(username)
            if member:
                await thread.add_user(member)
            else:
                log.warning("Discord user %s not found in %s", username, self.guild.name)
        self._remember(channel, thread)
        return thread.mention

    async def ensure_adviser(self, faction: str, username: str | None) -> str | None:
        import discord
        channel = f"adviser:{faction}"
        thread = self.threads.get(channel)
        if thread is None:
            thread = await self.table.create_thread(
                name=f"adviser ↔ {faction}", type=discord.ChannelType.private_thread, invitable=False)
            self._remember(channel, thread)
        # (re)add the adviser every time: an adopted thread, or one made before they joined the
        # server, may not have them yet; adding an existing member is harmless
        member = username and (discord.utils.get(self.guild.members, name=username)
                               or await self._fetch_member(username))
        if member:
            await thread.add_user(member)
        else:
            log.warning("adviser %s for %s not found in %s", username, faction, self.guild.name)
        return thread.mention

    async def _fetch_member(self, username: str):
        found = await self.guild.query_members(query=username, limit=5)
        return next((m for m in found if m.name == username), None)

    async def send(self, channel: str, text: str) -> None:
        import discord
        target = {"lobby": self.table, "chronicle": self.chronicle}.get(channel) or self.threads[channel]
        try:
            await target.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound:
            if channel in self.threads:  # a deleted thread: forget it so it's recreated next pump
                del self.threads[channel]
            raise


def run_bot(config: GameConfig) -> None:
    import discord
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN is not set (put it in the untracked env file)")
    if config.discord is None:
        raise SystemExit("game config has no [discord] section")

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True  # to find humans by username and add them to private threads
    client = discord.Client(intents=intents)
    table = DiscordTable(client, config)
    try:
        lock = acquire_bot_lock(config.turn_root)  # noqa: F841  (held for the process's life)
    except RuntimeError as e:
        raise SystemExit(str(e))
    store = Store(config.turn_root / f"{config.game_id}.db")
    responder = Responder(store, {f: make_seat(s.brain) for f, s in config.seats.items()}, config)
    names = config.display_names()
    tasks: list[asyncio.Task] = []  # strong reference: asyncio keeps only weak ones

    async def pump_forever():
        attempts: dict[int, int] = {}
        while True:
            try:
                await pump_outbox(store, table, config.game_id, names, config.humans, attempts,
                                  advisers=config.advisers())
            except Exception:  # e.g. SQLite busy: log and keep pumping
                log.exception("outbox pump failed; retrying")
            await asyncio.sleep(PUMP_SECONDS)

    @client.event
    async def on_ready():
        # on_ready fires again after a reconnect that can't resume; start everything once
        if tasks:
            return
        await table.connect()
        log.info("connected to %s, #%s", table.guild.name, table.lobby.name)
        tasks.append(client.loop.create_task(pump_forever()))

    @client.event
    async def on_message(message):
        if not message.author.bot and table.channel_for(message) == "lobby":
            reply = await private_command(table, config.humans, set(config.seats),
                                          message.author.name, message.content) \
                or await adviser_command(table, config.advisers(), message.author.name, message.content)
            if reply is not None:
                await message.reply(reply, allowed_mentions=discord.AllowedMentions.none())
                return
        await handle_incoming(responder, config.humans, message.author.name, message.author.bot,
                              table.channel_for(message), message.content, advisers=config.advisers())

    client.run(token, log_handler=None)
