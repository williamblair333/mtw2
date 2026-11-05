# Product: Parley

## Core job

A Medieval II player plays a whole campaign against rulers that think, negotiate in Discord and
act in the game, with no human keeping the game running.

## Users

1. **The author**, now: plays against LLM rulers and advises one, on his own Linux machine.
2. **Friends**, next: humans and LLMs share one campaign through the Discord table.
3. **Total War modders and players**, after release: they run their own campaigns and file bugs.

What they already have: Linux with Steam and *Medieval II: Total War – Definitive Edition*, a
Discord server they own, and comfort in a terminal. What they may not have: Proton set up for the
Windows build, EOP, a GPU for a local model, or paid API access. The first-run path assumes none
of those for the offline try-out, and points to the guide (`docs/WRITEUP.md` §3–4) for the real
game.

## Success

- **Unattended campaign:** a 2-seat campaign plays 100 turns with no human input (no click, no
  relaunch by hand). Tracked as turns per human intervention, per run; it must climb across runs.
- **Wishes carried out:** every ruler order is carried out or refused with a reason the ruler can
  act on (`just report <name>`: zero unexplained rejections).
- **No-click:** the newest no-click bench run (`just qa all kind=instant`) has no fail or
  inconclusive case before any turn work starts (STANDARDS `phase-order`).
- **Time to first result:** offline try-out (below) in **300 s** from a clean clone; real game,
  install to the first ruler turn answered, in **1800 s** for someone following the guide.

## First-run path

Offline try-out, no Medieval II and no LLM needed (two fake rulers play two simulated turns):

1. `git clone <this repo> && cd mtw2`
2. `pip install uv`
3. `uv sync`
4. `timeout 30 uv run python -m parley run games/example.toml 2>&1 & sleep 3; uv run python tools/fake_game.py --root runs/turns --game example --factions venice,milan --turns 2; wait`

The orchestrator logs `milan turn 2: 0 orders, 0 rejected` once the simulated game's turn
reports have been answered. The fake brains give no orders: this proves the turn pipeline, not a
ruler. The real game follows the guide, `docs/WRITEUP.md` §4.

Needs git and network: step 3 fetches Jigsaw from its public release tag
(`github.com/williamblair333/jigsaw`, v0.1.0).

## Non-goals

- The Feral Linux port: it can't run mods. Parley targets the Steam Windows build under Proton.
- Bundling EOP or M2EX: the installers download pinned releases from their authors.
- Rulers with hidden handicaps: rulers decide with full information; algorithms may do the work,
  but the ruler's wishes are always carried out.
- Screen clicks as a design: every action goes through EOP/Lua; a click is a named last resort.
- A deal ledger and cross-game memory (Plans 3 and 4) before the release: deferred.

## UI principles

- The interfaces are `just` recipes, the Discord table and the logs. Every recipe has a one-line
  description in `just --list`.
- A refusal says why and what to do next: an order is refused with a reason the ruler can act on;
  a recipe refuses with the command that fixes it (as `just qa` does for the phase-order gate).
- Nothing asks before acting during play: an unanswered decision is declined so autoplay never
  waits. Destructive steps (overwriting a save, replacing game files) back up first.
- Secrets are never typed into a chat or AI session: they go in the untracked env file from the
  user's own terminal.

## Verify

```yaml
verify:
  image: python:3.13   # has git: the first step is a clone, and uv fetches Jigsaw with git
  network: required
  install:
    - pip install uv
    - uv sync
  run: timeout 30 uv run python -m parley run games/example.toml 2>&1 & sleep 3; uv run python tools/fake_game.py --root runs/turns --game example --factions venice,milan --turns 2; wait
  expect:
    - stdout_contains: "milan turn 2: 0 orders, 0 rejected"
    - file: runs/turns/example/turn-0002/milan/orders.json
  time_target_seconds: 300
```
