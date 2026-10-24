# Plan 1: Game Bridge & Core Turn Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An LLM faction takes a turn: the game writes a state report, a seat (Claude, Ollama or Gemini) answers with validated orders, the game applies them, and the results are archived. It's proven first against a simulated game, then in M2EX.

**Architecture:** A Lua script inside M2EX (EOP-style API) and a Python orchestrator talk through JSON files in a shared turn directory, written atomically. The orchestrator turns a state report into a prompt and asks the faction's seat for orders in a fixed JSON schema. It checks every order against the report before writing the orders file, and backs up the save before each turn. The Lua side re-checks each order against the live game, applies what's valid, and reports what isn't.

**Tech Stack:** Python 3.13, uv, pydantic v2, httpx (Ollama), pytest; `claude` CLI (`-p --output-format json --json-schema`), `agy` CLI (`-p --output-format stream-json --json-schema`); M2EX Lua (LuaJIT, EOP API); `just`.

**Spec:** `docs/superpowers/specs/2026-10-23-llm-diplomacy-design.md`

**Later plans (not this one):** 2: Discord table and personas · 3: deals, transfers with delay, ledger · 4: reputation and memory across games · 5: scenarios.

## Global Constraints

- Python package `parley/`, tests in `tests/`, Lua in `lua/`. Run everything through `just` recipes.
- No secrets in the repo. Read them from the untracked root env file via environment variables `ANTHROPIC_API_KEY`, `OLLAMA_HOST`, `MTW2_GAME_DIR`.
- v1 control level: **ruler**. The game's AI plays routine moves, and the LLM gives diplomacy and specific override orders only. The orders schema must accept new order types later without breaking old ones.
- Bad orders never crash the game: they're rejected and reported back, never forced through (spec §1).
- Every turn's report, prompt, raw answer, orders and results are kept on disk (spec §2).
- Back up the save before every LLM turn, and keep the last 20 (spec §2, anti-goal 5).
- Default turn budget: 120 s per seat. LLM seats decide in parallel when the game allows it (anti-goal 4).
- The Lua side must not trust Python: it re-checks every order against the live game.

## Review Focus

1. **A truncated or half-written JSON file** (a crash mid-write): the reader must never act on it. Files are written to `*.tmp` and renamed. Test in Task 2.
2. **An LLM answer that isn't valid JSON, or orders that refer to things it doesn't own** (another faction's settlement, more gold than its treasury): reject the order, record the reason, and still end the turn cleanly. Tests in Tasks 1 and 3.
3. **A seat that times out or errors** (Ollama down, `claude` rate-limited): the faction gets an empty order set with the reason recorded, the turn still ends, and the game doesn't wait forever. Tests in Tasks 4 and 5.
4. **An orchestrator restarted mid-turn:** it picks up a state report with no orders yet and answers it once, never twice. Test in Task 5.
5. **Faction or settlement names with spaces, accents or mixed case** (e.g. `Holy Roman Empire`, `Zaragoza`): IDs come from the game's internal names, never display names. Test in Task 1.

---

### Task 1: Protocol models and order validation

**Files:**
- Create: `pyproject.toml`, `parley/__init__.py`, `parley/protocol.py`, `parley/validate.py`
- Modify: `justfile` (add `setup`, `test`)
- Test: `tests/test_protocol.py`, `tests/test_validate.py`, `tests/fixtures/state_turn1_venice.json`

**Interfaces:**
- Produces (in `parley/protocol.py`, pydantic v2, `PROTOCOL_VERSION = 1`):
  - `Settlement(id: str, name: str, region: str, garrison_strength: int, population: int, buildings: list[str])`
  - `Army(id: str, leader: str | None, x: int, y: int, strength: int, units: int, in_settlement: str | None)`
  - `FactionView(id: str, name: str, stance: Literal["war","peace","alliance","neutral"])`
  - `StateReport(protocol: int, game_id: str, turn: int, year: int, faction: str, treasury: int, income: int, settlements: list[Settlement], armies: list[Army], factions: list[FactionView], visible_enemies: list[Army], last_results: list[OrderResult])`
  - Orders: a pydantic discriminated union on `type`: `SendGold(type="send_gold", to: str, amount: int)`, `CedeSettlement(type="cede_settlement", settlement: str, to: str)`, `SetStance(type="set_stance", to: str, stance: Literal["war","peace","alliance"])`, `MarchOn(type="march_on", army: str, target_settlement: str)`, `Besiege(type="besiege", army: str, settlement: str)`, `Withdraw(type="withdraw", army: str, to_settlement: str)`
  - `Orders(protocol: int, game_id: str, turn: int, faction: str, orders: list[Order], note: str = "")`, where `note` is the LLM's private reasoning, kept in the archive
  - `OrderResult(index: int, type: str, ok: bool, reason: str = "")`
  - `orders_json_schema() -> dict`: the JSON Schema handed to the LLM CLIs
- Produces (in `parley/validate.py`): `validate_orders(report: StateReport, orders: Orders) -> tuple[Orders, list[OrderResult]]`. It returns the orders that survive, plus a rejected result for each one dropped.

- [ ] **Step 1: Write the failing tests.** `tests/fixtures/state_turn1_venice.json` is a valid report for faction `venice`, treasury 5000, owning settlements `venice` and `ragusa`, army `a1` in `venice`, and factions `milan` (peace) and `hre` (`Holy Roman Empire`, war).
  - `test_report_roundtrip`: load the fixture → `StateReport` → dump → load gives an equal object.
  - `test_unknown_order_type_rejected_by_schema`: `Orders.model_validate` with `{"type":"teleport"}` raises `ValidationError`.
  - `test_schema_is_json_schema`: `orders_json_schema()["$defs"]` has entries for all six order types.
  - `test_validate_gold_over_treasury`: `SendGold(to="milan", amount=6000)` → dropped, reason contains `"treasury"`.
  - `test_validate_cede_unowned`: `CedeSettlement(settlement="milan", to="hre")` → dropped, reason contains `"not owned"`.
  - `test_validate_unknown_faction`: `SetStance(to="atlantis", stance="war")` → dropped, reason contains `"unknown faction"`.
  - `test_validate_unknown_army`: `MarchOn(army="zz", target_settlement="ragusa")` → dropped.
  - `test_validate_ids_not_display_names`: `SetStance(to="Holy Roman Empire", ...)` → dropped (`unknown faction`). `to="hre"` → kept.
  - `test_validate_keeps_good_orders_in_order`: a mix of 2 good and 1 bad order → 2 kept in their original order. Result `index` values point to the original positions.
- [ ] **Step 2:** `just test` → FAIL (module missing).
- [ ] **Step 3: Implement.** `pyproject.toml`: project `parley`, Python `>=3.13`, deps `pydantic>=2.8`, `httpx>=0.27`, dev `pytest>=8`. The `justfile` gets `setup: uv sync` and `test: uv run pytest -q`. Gold transfers also need `amount > 0`. A faction can't target itself.
- [ ] **Step 4:** `just test` → all PASS.
- [ ] **Step 5: Commit.** `feat: protocol models and order validation`

### Task 2: File bridge with atomic writes

**Files:**
- Create: `parley/bridge.py`
- Test: `tests/test_bridge.py`

**Interfaces:**
- Consumes: `StateReport`, `Orders`, `OrderResult` (Task 1).
- Produces: `TurnDir(root: Path)` with:
  - `path_for(game_id: str, turn: int, faction: str) -> Path`, i.e. `root/<game_id>/turn-<0000>/<faction>/`
  - `pending() -> list[Path]`: faction dirs that have `state.json` and no `orders.json`, sorted by turn then faction
  - `read_state(dir: Path) -> StateReport`
  - `write_orders(dir: Path, orders: Orders) -> None`
  - `write_artifact(dir: Path, name: str, text: str) -> None`, for the prompt, raw answer and so on
  - `read_results(dir: Path) -> list[OrderResult] | None`
- Every write goes to `<name>.tmp`, then `fsync`, then `os.replace`. Readers ignore `*.tmp`.

- [ ] **Step 1: Write the failing tests:**
  - `test_pending_lists_unanswered_only`: two faction dirs, one already answered → `pending()` returns only the other.
  - `test_tmp_files_ignored`: a dir holding only `state.json.tmp` isn't pending.
  - `test_write_orders_atomic`: after `write_orders`, no `.tmp` remains, and `orders.json` parses back to the same `Orders`.
  - `test_read_state_truncated_raises`: a truncated `state.json` raises `ValueError`. The caller decides whether to retry.
- [ ] **Step 2:** `just test` → FAIL.
- [ ] **Step 3:** Implement per the interface.
- [ ] **Step 4:** `just test` → PASS.
- [ ] **Step 5: Commit.** `feat: atomic file bridge`

### Task 3: Prompt builder

**Files:**
- Create: `parley/prompt.py`
- Test: `tests/test_prompt.py`

**Interfaces:**
- Consumes: `StateReport`, `OrderResult`, `orders_json_schema()`.
- Produces: `build_prompt(report: StateReport, persona: str, scenario: str = "") -> str`.

The prompt is plain text in this order: persona → scenario (if any) → role ("You are the ruler. Your generals handle routine moves. Give only diplomatic and specific override orders.") → turn and year → treasury and income → own settlements → own armies → other factions with stances → visible enemies → last turn's results, including rejected orders and their reasons → output rules. The output rules say: return JSON matching the schema, use IDs exactly as written, never claim resources you don't have, and an empty `orders` list is allowed. Each entity appears as `id (Display Name)` so the LLM sees which string to use.

- [ ] **Step 1: Write the failing tests** with the Task 1 fixture:
  - `test_prompt_lists_ids`: contains `"hre (Holy Roman Empire)"` and `"venice"`.
  - `test_prompt_includes_rejections`: a report with `last_results=[OrderResult(index=0,type="send_gold",ok=False,reason="treasury too low")]` → prompt contains `"treasury too low"`.
  - `test_prompt_includes_scenario_when_given`: and omits the scenario section when it's empty.
  - `test_prompt_states_treasury`: contains `"5000"`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5: Commit.** `feat: prompt builder`

### Task 4: Seats (Claude Code, Ollama, Gemini via agy, fake)

**Files:**
- Create: `parley/seats/__init__.py`, `parley/seats/base.py`, `parley/seats/claude_code.py`, `parley/seats/ollama.py`, `parley/seats/agy.py`, `parley/seats/fake.py`
- Test: `tests/test_seats.py`, `tests/fixtures/claude_result.json`, `tests/fixtures/agy_stream.jsonl`

**Interfaces:**
- Consumes: `Orders`, `orders_json_schema()`.
- Produces:
  - `class SeatError(Exception)`
  - `class Seat(Protocol)` with `name: str` and `decide(prompt: str, *, game_id: str, turn: int, faction: str, timeout: float) -> tuple[Orders, str]`. It returns the parsed orders and the raw answer text, and raises `SeatError` on timeout, a process error or unparseable output.
  - `ClaudeCodeSeat(model: str = "sonnet")`: runs `claude -p <prompt> --output-format json --json-schema <schema-json> --model <model> --tools ""`, so the seat can't touch the machine. It parses the result object's structured output (take the field name from a live run, recorded as the fixture).
  - `OllamaSeat(model: str = "qwen3.5:9b", host: str = $OLLAMA_HOST)`: POSTs `/api/chat` with `format=<schema>` and `stream=false`.
  - `AgySeat(model: str = "gemini-4-argon-medium")`: runs `agy -p <prompt> --output-format stream-json --json-schema <schema-json> --model <model> --print-timeout <timeout>s` and takes the `result` event's response, the same parsing as `local tooling/scripts/ask_agy.py::ask`.
  - `FakeSeat(script: list[Orders | Exception])`: returns or raises the next item, for tests.
  - `make_seat(spec: str) -> Seat`, where spec is `"claude:sonnet"`, `"ollama:qwen3.5:9b"`, `"agy:gemini-4-argon-medium"` or `"fake"`.
  - Each seat fills in `game_id`, `turn` and `faction` in the returned `Orders`, overriding whatever the LLM wrote.

- [ ] **Step 0: Record fixtures from live runs.** Run each CLI once with a tiny schema (`{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"]}`), save the raw stdout as `tests/fixtures/claude_result.json` and `tests/fixtures/agy_stream.jsonl`, and note the structured-output field name.
- [ ] **Step 1: Write the failing tests.** Subprocess and httpx get mocked, so tests never call a real LLM:
  - `test_claude_parses_fixture`: mocked `subprocess.run` returns the fixture → `Orders` parsed.
  - `test_claude_timeout_raises_seat_error`: `subprocess.TimeoutExpired` → `SeatError`.
  - `test_ollama_bad_json_raises_seat_error`: the mocked response body is `"not json"` → `SeatError`.
  - `test_agy_no_result_event_raises`: a stream with no `result` event → `SeatError`.
  - `test_identity_fields_overwritten`: the LLM returns `faction="milan"` for a venice turn → the returned `Orders.faction == "venice"`.
  - `test_make_seat_specs`: each spec string returns the right class. `"bogus:x"` raises `ValueError`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5: Live smoke test (manual, not in `just test`).** Add the recipe `just seat-smoke <spec>`, which sends the fixture report's prompt to one real seat and prints the orders. Run it for `claude:sonnet`, `ollama:qwen3.5:9b` and `agy:gemini-4-argon-medium`. Expected: each prints valid `Orders` within 120 s. Record any failures in HANDOFF.
- [ ] **Step 6: Commit.** `feat: seat adapters for claude, ollama, agy`

### Task 5: Orchestrator, simulated game and save backups

**Files:**
- Create: `parley/orchestrator.py`, `parley/saves.py`, `parley/config.py`, `parley/__main__.py`, `tools/fake_game.py`, `games/example.toml`
- Modify: `justfile` (add `run game="games/example.toml"` and `fake-game`)
- Test: `tests/test_orchestrator.py`, `tests/test_saves.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - `GameConfig` (in `config.py`, loaded from TOML): `game_id: str`, `turn_root: Path`, `save_dir: Path`, `seat_timeout: float = 120`, `keep_backups: int = 20`, `seats: dict[str, SeatConfig]` keyed by faction ID. `SeatConfig(brain: str, persona: str)`, where `brain` is a `make_seat` spec. `load_config(path: Path) -> GameConfig`.
  - `backup_saves(save_dir: Path, backup_root: Path, label: str, keep: int) -> Path`, which copies the newest `*.sav` to `backup_root/<label>-<filename>` and prunes the oldest beyond `keep`.
  - `Orchestrator(config: GameConfig, seats: dict[str, Seat])` with `run_once() -> int`. That handles all pending dirs, LLM factions in parallel (thread pool, one worker per seat), and returns how many it answered. `run_forever(poll: float = 0.5) -> None`.
  - Per pending dir: back up saves, build the prompt, write `prompt.txt`, call the seat with a timeout, write `answer.txt`, run `validate_orders`, write `orders.json` (kept orders) and `rejected.json`. On `SeatError`, write empty `Orders` with `note="seat error: <msg>"`. A pending dir whose faction isn't in `config.seats` is skipped and logged (it's a human or the game's AI).
  - `tools/fake_game.py --root <turn_root> --game <id> --factions venice,milan --turns 3`: writes a fixture-style `state.json` per faction per turn, waits for `orders.json`, writes `results.json` (all ok), and goes to the next turn.
  - `python -m parley run <game.toml>` starts `run_forever`.

- [ ] **Step 1: Write the failing tests** with `FakeSeat` and `tmp_path`:
  - `test_answers_each_pending_once`: two pending factions → `run_once()==2`. A second `run_once()==0`.
  - `test_restart_mid_turn_no_double_answer`: one dir already has `orders.json` and another doesn't → only the second is answered.
  - `test_seat_error_still_ends_turn`: the `FakeSeat` raises `SeatError("down")` → `orders.json` exists with empty orders and the note contains `"down"`.
  - `test_invalid_orders_filtered_and_recorded`: the seat returns one bad and one good order → `orders.json` has 1 order and `rejected.json` has 1 with its reason.
  - `test_artifacts_written`: `prompt.txt` and `answer.txt` exist.
  - `test_unconfigured_faction_skipped`.
  - `test_backup_rotation`: 25 calls with `keep=20` → 20 files remain, newest kept.
  - `test_parallel_seats`: two `FakeSeat`s that each sleep 1 s → `run_once()` takes < 1.8 s.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5: End-to-end against the fake game.** In one terminal run `just fake-game`, in the other `just run games/example.toml`, with the example config using `fake` seats. Expected: the fake game reaches turn 3 and exits 0, and each turn dir holds state, prompt, answer, orders, rejected and results.
- [ ] **Step 6: Commit.** `feat: orchestrator with simulated game and save backups`

### Task 6: Game setup and Lua bridge probe (needs the author's machine)

**Prerequisite:** the author has switched the game to Proton 10+ and the Windows build has downloaded. Gemini's EOP research (`_review/2026-10-23-gemini-eop-api-research.md`) is verified by Claude against the EOP docs and source, and the verified function names are copied into `docs/eop-api-notes.md` (committed). This task and Task 7 use only names listed there.

**Files:**
- Create: `scripts/install_m2ex.sh`, `lua/parley_probe.lua`, `docs/eop-api-notes.md`
- Modify: `justfile` (add `install-m2ex`, `probe`), `README.md` (setup steps)

**Interfaces:**
- Produces: a written answer, in `docs/eop-api-notes.md`, to: (a) can Lua write and read files, and with which path base; (b) which event fires at the start of each faction's turn, and does it fire for hotseat slots; (c) can a script hand a hotseat slot's turn to the game's AI, or should LLM factions stay AI factions with override orders; (d) can Lua block or poll for up to 120 s without freezing rendering, or must it use a per-frame or tick callback.

- [ ] **Step 1:** `scripts/install_m2ex.sh` downloads the pinned M2EX release asset from `github.com/Pannoniae/rex/releases` (tag pinned in the script), checks its SHA-256, backs up any files it would replace into `$MTW2_GAME_DIR/.parley-backup/<date>/`, and extracts it into `$MTW2_GAME_DIR`. `just install-m2ex` runs it. It refuses to run if `medieval2.exe` is missing, which means the Feral build is still installed.
- [ ] **Step 2:** `lua/parley_probe.lua` writes `probe.json` (turn, faction, treasury) at each faction turn start, then waits for `probe_ack.json` using the method chosen in (d). `just probe` copies it to where M2EX autoloads EOP scripts.
- [ ] **Step 3: Manual run.** the author starts a hotseat campaign with 2 human slots and autoresolve on, then ends turn once. Expected: `probe.json` appears for the second slot, and creating `probe_ack.json` by hand lets the game go on. Record (a)–(d) in `docs/eop-api-notes.md`.
- [ ] **Step 4: Decision point.** If (a) is "no", stop and bring the fallback (native plugin or another channel) back to the author as a design change. If (c) means LLM factions stay as AI factions, record that in the spec's §0 under the existing "Open technical question" bullet.
- [ ] **Step 5: Commit.** `feat: M2EX install script and Lua bridge probe`

### Task 7: Lua bridge (live game)

**Prerequisite:** Task 6 answered (a)–(d).

**Files:**
- Create: `lua/parley_bridge.lua`, `lua/parley_json.lua` (vendored pure-Lua JSON, MIT licensed, with a license header)
- Modify: `justfile` (`install-bridge`), `games/example.toml`
- Test: `tests/test_lua_contract.py` (checks that a state report captured from the live game parses as `StateReport`), `tests/fixtures/live_state_sample.json`

**Interfaces:**
- Consumes: the file layout from Task 2 (exact paths), the protocol from Task 1, and the API names in `docs/eop-api-notes.md`.
- Produces: at the start of each turn for a faction listed in `parley_factions.txt` (written by the orchestrator at startup), the script writes `state.json` (atomic: `.tmp` then `os.rename`), waits up to `seat_timeout + 30` s for `orders.json`, applies each order after re-checking it against the live game (ownership, treasury, valid IDs), writes `results.json`, and ends the turn. If it times out, it applies nothing and writes `results.json` with every order `ok=false` and `reason="timeout"`. Any Lua error inside an order is caught with `pcall` and becomes that order's `ok=false`.
- `send_gold` in v1 moves the money **immediately**. The delayed transfer comes in Plan 3, which wraps this.

- [ ] **Step 1:** Capture a live `state.json` with the Task 6 probe extended to the full report, save it as `tests/fixtures/live_state_sample.json`, and write `test_live_sample_parses`. Run `just test` and fix field mismatches on the Lua side.
- [ ] **Step 2:** Implement the order handlers one type at a time, in this order: `set_stance`, `send_gold`, `cede_settlement`, `withdraw`, `march_on`, `besiege`. After each one, run a manual check in game with a `fake` seat scripted to issue that order, and confirm the effect on the campaign map.
- [ ] **Step 3: Crash test.** Script a seat to send bad orders (unknown IDs, gold over the treasury, besieging its own settlement). Expected: the game keeps running and `results.json` shows each one rejected with a reason.
- [ ] **Step 4: Live end-to-end.** the author plays England. Venice is `claude:sonnet` and Milan is `ollama:qwen3.5:9b`, for 5 turns. Expected: each LLM turn completes within 120 s, no crashes, the archive is complete, and the save backups rotate.
- [ ] **Step 5: Commit.** `feat: live Lua bridge for ruler-level orders`. Update CHANGELOG, HANDOFF and ROADMAP.
