"""Between-turn conversation: when a human speaks to an LLM ruler, that ruler answers.

Who answers:
- in a private thread: the LLM on the other side, when the sender is the human there;
- in the lobby: every LLM whose faction ID or persona name is mentioned;
- in an adviser thread: the ruler, when the sender is its adviser.
LLM messages never trigger replies (no bot loops), and each LLM has a per-turn reply cap.
"""

import asyncio
import logging
import re

from parley.bridge import TurnDir
from parley.config import GameConfig
from parley.prompt import one_line
from parley.store import Message, Store, adviser_channel
from parley.seats import Seat, SeatError

log = logging.getLogger("parley.chat")
MAX_REPLIES_PER_TURN = 6
MAX_CHARS = 600


TITLES = {"emperor", "empress", "king", "queen", "pope", "doge", "duke", "duchess", "count",
          "countess", "prince", "princess", "grand", "sultan", "vizier", "caliph", "emir", "lord",
          "lady", "archbishop", "bishop", "brother", "sir", "signore", "the", "of", "and"}
ROMAN = re.compile(r"^[ivxlc]+$")


def _key_words(name: str) -> set[str]:
    """Distinctive words of a persona name: no titles, numerals or short words."""
    words = re.findall(r"[\w'-]+", name.lower())
    return {w for w in words for part in [w.split("-")[-1]]
            if part not in TITLES and w not in TITLES and not ROMAN.match(w) and len(w) >= 4}


def mentions(text: str, names: dict[str, str]) -> list[str]:
    """Factions addressed in `text`: by faction id ("papal_states" or "papal states") or by any
    distinctive word of the ruler's name ("Henry" for "Emperor Henry IV"). Titles alone don't count."""
    said = set(re.findall(r"[\w'-]+", text.lower()))
    flat = " ".join(text.lower().split())
    hits = []
    for faction, name in names.items():
        by_id = faction in said or faction.replace("_", " ") in flat
        if by_id or (_key_words(name) & said):
            hits.append(faction)
    return sorted(hits)


def _label(m: Message, names: dict[str, str]) -> str:
    from parley.prompt import _sender
    return _sender(m.sender, names)


def _where(channel: str, me: str, names: dict[str, str] | None = None) -> str:
    if channel == "lobby":
        return "the public lobby (everyone reads it)"
    if channel.startswith("adviser:"):
        who = (names or {}).get(channel, "your adviser")
        return (f"your private thread with your loyal adviser {who} (only the two of you read it). "
                "They want you to win: weigh their counsel, agree or overrule it, and say why")
    a, b = channel.removeprefix("pair:").split("|")
    return f"a private thread with {b if a == me else a} (only the two of you read it)"


WHAT_IS_REAL = """WHAT YOU CAN ACTUALLY DO (on your next turn, through orders)
- send gold (only what your treasury holds), give one of your own settlements, set war/peace/alliance, move or besiege with your armies.
- Nothing else is enforced by the game: loans, interest, repayment, tolls, trade rights and pledges are only words. You may still bargain over them, but say plainly what you will actually do.
- Never promise more gold than your treasury. Never name a settlement, army or place you don't see in your report; if you don't know another faction's towns, ask."""


def chat_prompt(persona: str, faction: str, history: list[Message], incoming: Message,
                names: dict[str, str], report=None, areas: tuple[str, ...] | None = None) -> str:
    lines = [persona.strip(), "",
             f"You rule {faction}. You are speaking in {_where(incoming.channel, faction, names)}."]
    if report is not None:
        from parley.prompt import state_summary
        # which factions have a ruler and which the game's AI runs (live: a chat reply claimed
        # peace kept the AI's armies from assaulting, after two towns fell under it)
        ruled = {k for k in names if not k.startswith("adviser:")} or None
        summary = state_summary(report, areas, ruled) if areas else state_summary(report, ruled=ruled)
        lines += ["", "YOUR REALM (as of your last turn report)", *[p + "\n" for p in summary]]
    lines += ["", WHAT_IS_REAL]
    if history:
        from parley.prompt import _diplomacy_line
        lines += ["", "RECENT DIPLOMACY (most recent last)"]
        lines += [_diplomacy_line(m, faction, names) for m in history]
    rules = (f"Answer in character, in plain text, under {MAX_CHARS} characters. "
             "This is talk only: you can't give orders here, and promises bind nothing in the game. "
             "Never reveal your private reasoning in a public reply.")
    if incoming.channel.startswith("adviser:"):  # live: three promised marches, none ordered
        rules += (" To your adviser, don't promise orders: say what you ordered last turn and what you "
                  "will weigh. Your next turn reads this thread and must keep anything you do promise, "
                  "or tell them why not.")
    if incoming.channel == "lobby":
        rules += (" Everyone reads this reply: don't repeat private conversations or reveal your "
                  "garrisons and armies unless you mean to.")
    if not incoming.channel.startswith("adviser:") and any(m.channel.startswith("adviser:") for m in history):
        rules += " Never reveal your adviser, or what they told you, to anyone else."
    lines += ["", "NEW MESSAGE TO ANSWER", f"{_label(incoming, names)}: {one_line(incoming.text)}", "",
              rules]
    return "\n".join(lines) + "\n"


class Responder:
    def __init__(self, store: Store, seats: dict[str, Seat], config: GameConfig):
        self.store, self.seats, self.config = store, seats, config
        self.pending: dict[tuple[str, int], int] = {}  # replies being written right now

    def _reserve(self, faction: str, turn: int) -> bool:
        """Claim a reply slot before calling the LLM, so a burst of messages can't overrun the
        cap. Posted replies are counted from the store, so the cap survives restarts."""
        key = (faction, turn)
        used = self.store.chat_count(self.config.game_id, turn, faction) + self.pending.get(key, 0)
        if used >= MAX_REPLIES_PER_TURN:
            return False
        self.pending[key] = self.pending.get(key, 0) + 1
        return True

    def _release(self, faction: str, turn: int) -> None:
        self.pending[(faction, turn)] -= 1

    def _turn(self) -> int:
        try:
            text = (self.config.turn_root / "heartbeat.txt").read_text()
            return int(text.strip().removeprefix("turn="))
        except (OSError, ValueError):
            return 0

    def _latest_report(self, faction: str):
        """The faction's newest turn report, so chat matches what it really has."""
        turns = TurnDir(self.config.turn_root)
        game_dir = self.config.turn_root / self.config.game_id
        for t in sorted(game_dir.glob("turn-*"), reverse=True):
            if (t / faction / "state.json").exists():
                try:
                    return turns.read_state(t / faction)
                except (ValueError, OSError):
                    continue
        return None

    def _addressees(self, channel: str, sender: str, text: str) -> list[str]:
        if sender.startswith("adviser:"):  # an adviser talks only to its own ruler
            faction = sender.removeprefix("adviser:")
            return [faction] if channel == adviser_channel(faction) and faction in self.seats else []
        if not sender.startswith("human:"):
            return []
        if channel == "lobby":
            return [f for f in mentions(text, {f: s.name for f, s in self.config.seats.items()})
                    if f in self.seats]
        human = sender.removeprefix("human:")
        a, b = channel.removeprefix("pair:").split("|")
        other = b if a == human else a if b == human else None
        return [other] if other in self.seats else []

    async def on_incoming(self, channel: str, sender: str, text: str) -> list[Message]:
        turn = self._turn()
        game = self.config.game_id
        msg_id = self.store.record(game, turn, channel, sender, text)
        incoming = Message(msg_id, game, turn, channel, sender, text, 0)
        names = self.config.display_names()
        out = []
        for faction in self._addressees(channel, sender, text):
            if not self._reserve(faction, turn):
                log.info("%s reached its reply cap for turn %d", faction, turn)
                continue
            try:
                history = [m for m in self.store.recent(game, faction) if m.id != msg_id]
                prompt = chat_prompt(self.config.seats[faction].persona, faction, history, incoming,
                                     names, report=self._latest_report(faction),
                                     areas=self.config.seats[faction].areas)
                try:
                    reply = await asyncio.to_thread(self.seats[faction].chat, prompt,
                                                    timeout=self.config.seat_timeout)
                except SeatError as e:
                    log.error("%s could not reply: %s", faction, e)
                    continue
                reply = reply.strip()[:MAX_CHARS]
                if not reply:
                    continue
                row = self.store.queue(game, turn, channel, faction, reply, kind="chat")
                out.append(Message(row, game, turn, channel, faction, reply, 0))
            finally:
                self._release(faction, turn)
        return out
