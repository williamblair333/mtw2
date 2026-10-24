# Parley: LLM rulers and Discord diplomacy for Medieval II

Play *Medieval II: Total War* against rulers that think and talk. LLMs (Claude, Gemini, or a
local model) rule some factions and humans rule others. Everyone negotiates in Discord, in
public or in private. Deals are only words; whether a ruler honours one shows up in the game.

**Status:** playable on Linux. The game-side bridge works (all 8 order types verified in game),
the Discord table works (public channel per game, private threads, replies between turns), and
rulers remember their notes and what happened to them. There's a persona library with historic
1080 rulers and permanent archetypes.

**→ Full guide: [`docs/WRITEUP.md`](docs/WRITEUP.md)**. Start with §0, the runbook (stop a game, start a new one), then install (§4), play, configure and troubleshoot.
Build log: [`docs/JOURNAL.md`](docs/JOURNAL.md).

## Quick start (after the one-time install in the guide)

```sh
just run games/historic-1080.toml       # the turn loop
just discord games/historic-1080.toml   # the Discord bot (in your own terminal)
# Steam: Play → Run Mod → new Grand Campaign as England
just notes                              # god view: rulers' private notes
```

## Recipes

| Recipe | What it does |
|---|---|
| `just setup` | install Python dependencies |
| `just test` | run the test suite (includes the Lua bridge in LuaJIT) |
| `just install-eop` / `install-bridge` | install EOP 3.3.1 and the bridge into the game |
| `just install-m2ex` / `probe` | optional M2EX install; Lua environment probe |
| `just run <game.toml>` | the orchestrator: answers LLM rulers' turns |
| `just discord <game.toml>` | the Discord table bot (needs `DISCORD_BOT_TOKEN` in the untracked env file) |
| `just notes [faction] [last]` | rulers' private notes, orders and messages |
| `just fake-game` / `seat-smoke <brain>` | the simulated game; ask one real LLM seat for orders |

## Configuration

Game files live in `games/`. The shipped ones use placeholders: `your_discord_name` and
`My Parley Server`. Copy one into `games/local/`, which is gitignored, and fill in your Discord
username and server name there. Secrets live only in the untracked env file at the repo root
(`DISCORD_BOT_TOKEN`, optionally `ANTHROPIC_API_KEY`, `OLLAMA_HOST`). See the guide, §6.

## License

GPL-3.0 (see `LICENSE`), the same as [M2TWEOP](https://github.com/EOP-Labs/M2TWEOP-library), the
engine the game-side bridge runs in. The bundled `lua/vendor/json.lua` keeps its MIT license. M2EX
and EOP aren't bundled: the installers download the pinned releases from their authors.

Medieval II: Total War is a trademark of its owners. This is an unofficial fan project.
