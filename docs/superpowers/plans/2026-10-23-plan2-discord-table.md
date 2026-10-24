# Plan 2: Discord Table — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rulers talk. LLM factions post public messages in `#lobby` and private messages in per-pair private threads. They read what humans and other LLMs said, answer humans directly between turns, and see the conversation in their turn report.

**Architecture:** Two processes share one SQLite file (`<turn_root>/<game_id>.db`). The orchestrator (Plan 1) puts each faction's outgoing messages in an **outbox** table and adds recent **diplomacy** to each prompt. A new Discord bot process (`parley discord <game.toml>`) posts outbox rows, records every message people write in `#lobby` and the private threads, and asks a faction's seat for a quick **chat reply** when a human speaks to it. All Discord calls sit behind a small `Table` interface, so the core logic is tested without Discord.

**Tech Stack:** Python 3.13, `discord.py>=2.4`, `sqlite3` (stdlib), pytest. Plan 1's seats gain a free-text `chat()`.

**Spec:** `docs/superpowers/specs/2026-10-23-llm-diplomacy-design.md` (§3 Discord, §5 memory). Plan 1: `docs/superpowers/plans/2026-10-23-plan1-bridge-and-turn-loop.md`.

## Global Constraints

- The bot token is read only from the env var `DISCORD_BOT_TOKEN` (untracked env file). Never log it.
- One bot speaks for every LLM. Each message is prefixed `**<persona name> (<Faction>):**`. Per-persona webhooks are later work.
- `#lobby` is public, and anything said there is a public statement. Private threads are named `<a> ↔ <b>`, with the factions in alphabetical order. Humans are added to their own faction's threads. LLM-only threads have no human members (the server owner can still see them for debugging).
- Limits, so bots don't talk forever:
  - an LLM may send at most **3 messages per recipient per turn** (the lobby counts as one recipient);
  - at most **600 characters** per message;
  - chat replies are capped at **6 per faction per turn**, which is enough to hold a short negotiation with a human.
- Talk is free. Nothing a message says changes the game (spec §4). Deals and the ledger are Plan 3.
- Humans are mapped by Discord username in the game config: `[humans] england = "billdiscord"`.
- Seats stay backend-agnostic. `chat()` takes plain text in and returns plain text out.

## Review Focus

1. **A message refers to a faction that isn't in the game, or to the sender itself.** It's rejected at validation with a reason, like a bad order, and never posted. Tested in Task 2.
2. **The bot is offline while the orchestrator runs.** The outbox keeps every row, and the bot posts them in order when it reconnects, never twice. Tested in Task 1 (outbox `posted` flag) and Task 5.
3. **A human message arrives while the faction's chat seat is busy or errors.** No crash, no reply flood. One reply per incoming message at most, within the cap. Tested in Task 4.
4. **A very long Discord message, or one containing @everyone or role mentions.** Outgoing text is trimmed to 600 characters and has mentions disabled (`allowed_mentions=none`). Incoming text is stored trimmed to 2,000 characters. Tested in Tasks 2 and 5.
5. **An LLM leaks its private note or invents things another faction said.** The note is never posted. The prompt labels every quoted message with its real sender and channel, so the LLM can't confuse public with private. Tested in Task 3.

---

### Task 1: Message store (SQLite)

**Files:** Create `parley/store.py`. Test `tests/test_store.py`.

**Interfaces — Produces:**
- `Message(id: int, game_id: str, turn: int, channel: str, sender: str, text: str, ts: float)`. `channel` is `"lobby"` or `"pair:<a>|<b>"` (alphabetical). `sender` is a faction ID, or `"human:<faction>"` for a human seat.
- `Store(path: Path)`, which creates its tables if they're missing:
  - `record(game_id, turn, channel, sender, text) -> int`
  - `recent(game_id, faction, limit=30) -> list[Message]`: the lobby plus every pair channel that includes `faction`, newest last
  - `queue(game_id, turn, channel, sender, text) -> int`: an outbox row
  - `unposted(game_id) -> list[Message]`: oldest first
  - `mark_posted(id) -> None`, which also records the message via `record` in the same transaction
  - `sent_count(game_id, turn, sender, channel) -> int`
- `pair_channel(a: str, b: str) -> str`

- [ ] **Step 1: Failing tests:**
  - `test_pair_channel_sorted`: `pair_channel("venice", "england") == "pair:england|venice"`.
  - `test_recent_scopes_to_faction`: messages in the lobby, `pair:england|venice` and `pair:hre|milan` → `recent(..., "venice")` returns the first two only.
  - `test_outbox_posts_once`: queue 2 rows; `unposted` returns both in order. After `mark_posted(first)`, `unposted` returns only the second, and `recent` includes the posted one.
  - `test_sent_count`: two queued rows from venice to the lobby on turn 3 → `sent_count == 2`. Turn 4 → 0.
  - `test_survives_reopen`: write, open a new `Store` on the same file, read the same rows.
- [ ] **Step 2:** `just test` → FAIL. **Step 3:** Implement. WAL mode, one connection per call, which makes it safe across the two processes. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: SQLite message store and outbox`.

### Task 2: Messages in the orders schema

**Files:** Modify `parley/protocol.py`, `parley/validate.py`. Test `tests/test_validate.py`, `tests/test_protocol.py`.

**Interfaces:**
- Consumes `StateReport` (Plan 1).
- Produces:
  - `Say(to: str, text: str)`, where `to` is `"lobby"` or a faction ID.
  - `Orders.messages: list[Say] = []`.
  - `validate_messages(report, messages, already_sent: Callable[[str], int]) -> tuple[list[Say], list[OrderResult]]`. Rejections are `OrderResult(type="say", index=<position in messages>)`. `validate_orders` is unchanged.

- [ ] **Step 1: Failing tests:**
  - `test_say_to_unknown_faction_rejected` ("unknown faction")
  - `test_say_to_self_rejected`
  - `test_say_to_lobby_ok`
  - `test_say_trimmed_to_600`: a kept message is trimmed, not rejected
  - `test_say_cap_per_recipient`: with `already_sent` returning 2, the 2nd of two messages to venice is rejected ("limit 3 per turn")
  - `test_schema_includes_messages`: `orders_json_schema()` has `messages`, and the strict schema keeps `to`/`text` required
- [ ] **Steps 2–4:** RED → implement → GREEN.
- [ ] **Step 5: Commit** `feat: say-messages in the orders schema, validated and capped`.

### Task 3: Diplomacy in the prompt; orchestrator queues outgoing messages

**Files:** Modify `parley/prompt.py`, `parley/orchestrator.py`, `parley/config.py`. Test `tests/test_prompt.py`, `tests/test_orchestrator.py`.

**Interfaces:**
- `build_prompt(report, persona, scenario="", diplomacy: list[Message] = [], names: dict[str, str] = {}) -> str`. It gains a section **DIPLOMACY (most recent last)** with one line per message: `[turn T] [public] Doge Enrico (venice): …`, or `[turn T] [private with england] …`.
  - The section says plainly that public statements are seen by everyone, private ones only by the two sides, and that promises bind nothing in the game.
  - Output rules gain: put messages in `messages`, never put private reasoning in a message, and remember that order results show only that an order was carried out (check the next report for outcomes).
- `GameConfig` gains `humans: dict[str, str] = {}` (faction → Discord username) and `discord: DiscordConfig | None` (`guild`, `lobby="lobby"`, `chronicle="chronicle"`). `SeatConfig` gains `name: str` (persona display name, default = faction).
- The orchestrator gets `Store(turn_root / f"{game_id}.db")`. Per answered turn it:
  - passes `store.recent(...)` into the prompt;
  - validates messages with `already_sent` from `store.sent_count`;
  - queues the kept ones (`to == "lobby"` → `"lobby"`, otherwise `pair_channel(faction, to)`);
  - writes `messages.json` (kept and rejected) into the turn dir.

- [ ] **Step 1: Failing tests:**
  - `test_prompt_shows_diplomacy_labels`: public and private lines are labelled, with the persona name.
  - `test_prompt_says_promises_bind_nothing`.
  - `test_note_never_queued`: the seat returns a note and one message; the outbox holds only the message text.
  - `test_messages_queued_to_right_channel`: lobby → `"lobby"`, `to: "england"` → `"pair:england|venice"`.
  - `test_message_cap_across_turn`: a FakeSeat sends 4 to milan on one turn; 3 are queued and 1 is rejected in `messages.json`.
  - `test_config_humans_and_discord`: TOML with `[humans]` and `[discord]` loads.
- [ ] **Steps 2–4:** RED → implement → GREEN.
- [ ] **Step 5: Commit** `feat: diplomacy in prompts; orchestrator queues messages`.

### Task 4: Seats chat; chat responder

**Files:** Modify `parley/seats/*.py`. Create `parley/chat.py`. Test `tests/test_seats.py`, `tests/test_chat.py`.

**Interfaces:**
- `Seat.chat(prompt: str, *, timeout: float) -> str`:
  - Claude: `claude -p <prompt> --output-format json --model … --tools "" --strict-mcp-config --no-session-persistence`, taking `result`.
  - Ollama: `/api/chat` with no `format` and `think=false`.
  - agy: stream-json, taking `response`, under the same lock.
  - Fake: the next scripted string.
  - Script: `""`.
  - Raises `SeatError` like `decide`.
- `parley/chat.py`:
  - `chat_prompt(persona, name, faction, history: list[Message], incoming: Message, names) -> str`: the persona, then "you are speaking in <public lobby | private thread with X>", then the history labelled as in Task 3, then the incoming message, then the rules: answer in character, under 600 characters, no orders here, plain text only.
  - `Responder(store, seats, config)` with `async def on_incoming(msg: Message) -> list[Message]`. It records `msg`, then for each LLM faction that should answer it calls `seat.chat` in a thread with `seat_timeout`, queues the reply, and returns the queued rows.
  - **Should answer:**
    - in a pair channel: the LLM side when the sender is the human on the other side;
    - in the lobby: an LLM whose faction ID or persona name is mentioned (case-insensitive, word match).
  - Never answer an LLM's own message, and never answer when its per-turn chat cap is reached. The turn comes from `heartbeat.txt`.

- [ ] **Step 1: Failing tests:**
  - `test_claude_chat_parses_result` (fixture)
  - `test_ollama_chat_no_format`
  - `test_pair_message_from_human_gets_one_reply`
  - `test_lobby_mention_by_persona_name_replies`
  - `test_lobby_without_mention_no_reply`
  - `test_llm_message_never_triggers_reply`: no bot loops
  - `test_chat_cap_per_turn`: the 7th incoming message gets no reply
  - `test_seat_error_no_reply_no_crash`: logs, queues nothing
- [ ] **Steps 2–4:** RED → implement → GREEN.
- [ ] **Step 5: Commit** `feat: seat chat and the chat responder`.

### Task 5: Discord bot process

**Files:** Create `parley/discord_bot.py`. Modify `parley/__main__.py`, `pyproject.toml` (add `discord.py>=2.4`), `justfile` (`discord game=…`). Test `tests/test_discord_bot.py`, which uses a `FakeTable`. The thin discord.py layer is checked live in Task 6.

**Interfaces:**
- `class Table(Protocol)`:
  - `async def send(channel: str, text: str) -> None`
  - `async def ensure_pair(a: str, b: str, humans: list[str]) -> None`
- `DiscordTable(client, guild_name, lobby, humans)`:
  - finds `#lobby` by name;
  - finds or creates the private thread `"<a> ↔ <b>"` under it with `create_thread(name=…, type=discord.ChannelType.private_thread, invitable=False)`;
  - adds human members with `thread.add_user(member)`, looking members up by username;
  - sends with `allowed_mentions=discord.AllowedMentions.none()`;
  - keeps a map from thread ID to pair channel.
- `format_line(name, faction_display, text) -> str`: `**{name} ({faction_display}):** {text}`, trimmed to Discord's 2,000-character limit.
- `async def pump_outbox(store, table, game_id, names) -> int`: posts each unposted row in order, then `mark_posted`, and returns the count.
- `on_message` handler:
  - ignores bots;
  - maps the author to a human faction through `config.humans`, ignoring unmapped authors;
  - maps the channel (lobby or a known thread) to a store channel;
  - trims to 2,000 characters;
  - calls `Responder.on_incoming`.
- The outbox is pumped every 2 s.
- `python -m parley discord <game.toml>` and `just discord`.

- [ ] **Step 1: Failing tests (FakeTable):**
  - `test_pump_posts_in_order_once`
  - `test_pump_survives_send_error`: the row stays unposted and is retried next pump
  - `test_format_line_trims_and_names`
  - `test_pair_thread_created_before_first_private_post` (`ensure_pair` called once per pair)
  - `test_incoming_from_unmapped_user_ignored`
- [ ] **Steps 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** Pre-mortem (dependency, persistent writes). Add `discord.py` and the recipe.
- [ ] **Step 6: Commit** `feat: Discord bot process (lobby, private threads, outbox pump)`.

### Task 6: Live session — talk to Venice

- [ ] **Step 1:** the author tells us their Discord username, which goes into `games/first-game.toml` `[humans] england = "<username>"` and `[discord] guild = "My Parley Server"`.
- [ ] **Step 2:** Run `just run games/first-game.toml` and `just discord games/first-game.toml` (two processes). The author posts in `#lobby` "Venice, will you ally with England against the HRE?". Expected:
  - a reply signed **Doge Enrico (Venice)** within about 30 s;
  - on Venice's next turn, a lobby or thread message;
  - an alliance order, or a reasoned refusal.
- [ ] **Step 3:** the author writes in the private `england ↔ venice` thread. Expected: a private reply that doesn't appear in the lobby.
- [ ] **Step 4:** Let Venice and Milan talk for 3 turns. Check the caps hold (no more than 3 messages per pair per turn) and that the private threads stay private.
- [ ] **Step 5:** Journal, update the CHANGELOG and HANDOFF, then PR.
