# mtw2: agent notes

- The design lives in `docs/superpowers/specs/`. Read the newest spec before changing behavior.
- Use the `justfile` recipes. Add one-line recipes over scripts; keep logic out of the justfile.
- Secrets go only in the untracked env file at the repo root. Never commit them. The repo
  will go public later.
- `_review/` and `_reviewed/` are local and gitignored. Gemini research reports land in `_review/`.
- Gemini (via `agy`) takes research and grunt work. Verify its output before acting on it.
- The game is the Steam Windows build under Proton, with M2EX. The Feral Linux port can't run mods.
- Never commit directly to `main`. Branch, PR on Gitea, merge.
