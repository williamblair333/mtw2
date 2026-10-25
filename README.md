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
cp games/template.toml games/local/template.toml   # once: then set your Discord name + server in it
just new-game game3 --rivals 6 --scratch   # 6 random rivals, one secretly Old Scratch
just play game3          # start the turn loop + Discord bot for it
# Steam: Play → Run Mod → new Grand Campaign as England
just status              # what's running
just notes               # god view: rulers' private notes
just stop                # stop everything
```

More setups (`just new-game --help` prints the full list, and the guide §5a explains them):

```sh
just new-game game4 --play france hre papal_states            # exactly these rivals
just new-game game5 --rivals 5 --personas archetypes          # 5 different archetypes
just new-game game6 --rivals 5 --personas historic            # 5 rivals as their 1080 rulers
just new-game game7 --play all --brain flash                  # every faction, all on Gemini
just new-game game8 --play venice --seat venice=@rules-lawyer:opus
just new-game game9 --ask                                     # answer questions instead
```

To mod a faction, edit its block in `games/local/template.toml`: `persona`, `name`, `brain`.

## Recipes

| Recipe | What it does |
|---|---|
| `just new-game <name> [options]` | make a game from your template (`--help` for examples) |
| `just play <name>` / `stop` / `status` / `logs <name>` | run, stop and inspect a game |
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
