#!/usr/bin/env bash
# just run <game.toml>: answer LLM-faction turns as the game writes them, in the foreground.
# Borrows the logged-in desktop's display when started without one (over ssh): the loop
# screenshots the game's popups (live 11-05 14:56, the test laptop: "screenshot failed: game window
# not found", and every offer ran to its 540 s timeout).
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=desktop_env.sh
. scripts/desktop_env.sh
if desktop_env_borrow; then
    [ -n "${DESKTOP_ENV_FROM:-}" ] && echo "run: no display here; using the desktop's (DISPLAY=${DISPLAY:-}, from $DESKTOP_ENV_FROM)"
else
    echo "warning: nobody is logged in to the desktop; the turn loop can't see the game's popups" >&2
fi
exec uv run python -m parley run "$@"
