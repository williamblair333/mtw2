# mtw2: agent notes

- The design lives in `docs/superpowers/specs/`. Read the newest spec before changing behavior.
- Use the `justfile` recipes. Add one-line recipes over scripts; keep logic out of the justfile.
- Secrets go only in the untracked env file at the repo root. Never commit them. The repo
  will go public later.
- `_review/` and `_reviewed/` are local and gitignored. Gemini research reports land in `_review/`.
- Gemini (via `agy`) takes research, grunt work and test-backed code in a worktree. Verify its
  output before acting on it. In a worktree, `uv sync` on the host first, then Gemini tests with
  `sandbox-run .venv/bin/pytest -q` (`uv run` can't re-resolve the Jigsaw path offline).
- Parley depends on Jigsaw (`../jigsaw`, public; pinned to a git tag in pyproject.toml).
  Local Jigsaw edits don't reach Parley: merge and tag a release there, bump the tag here, `uv lock`.
- The game is the Steam Windows build under Proton, with M2EX. The Feral Linux port can't run mods.
- Never commit directly to `main`. Branch, PR on Gitea, merge.
