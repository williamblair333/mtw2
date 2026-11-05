#!/usr/bin/env bash
# Run QA bench suites in the live game on the fixed bench save (the real campaign parked on a kept
# copy of its save and restored after), restore, or make the bench save.
#   qa.sh run <suite|all> [--real games/local/<name>.toml] [case=NAME | --case NAME]... [--no-smoke]
#             [kind=instant | --kind instant]   (instant cases only; no clicks: PARLEY_NO_X_INPUT=1)
#   qa.sh restore [--real games/local/<name>.toml]
#   qa.sh bench-save start|record [--real games/local/<name>.toml] [--from <save>]
#             (record --from <save> with no start before it: no menu, no clicks)
set -euo pipefail

cd "$(dirname "$0")/.."
GAMES_DIR="${PARLEY_GAMES_DIR:-games/local}"

die() { echo "$*" >&2; exit 1; }

resolve_real_toml() {
    local candidate="${1:-}"
    if [ -n "$candidate" ]; then
        [[ "$candidate" == *.toml ]] || candidate="$GAMES_DIR/$candidate.toml"
        [ -f "$candidate" ] || die "no such game config: $candidate"
        echo "$candidate"
        return 0
    fi
    if [ -n "${QA_REAL_GAME:-}" ]; then
        candidate="$QA_REAL_GAME"
        [[ "$candidate" == *.toml ]] || candidate="$GAMES_DIR/$candidate.toml"
        [ -f "$candidate" ] || die "no such game config: $candidate"
        echo "$candidate"
        return 0
    fi
    candidate=$(bash scripts/game.sh status 2>/dev/null \
        | sed -n 's/.*running (\([^,)]*\.toml\), pid.*/\1/p' \
        | grep -v '/qa-' \
        | head -1 || true)
    if [ -n "$candidate" ] && [ -f "$candidate" ]; then
        echo "$candidate"
        return 0
    fi
    die "real loop is not running; pass --real games/local/<name>.toml or set QA_REAL_GAME"
}

cmd="${1:-}"
[ -n "$cmd" ] || die "usage: qa.sh run <suite|all> [--real <game.toml>] | restore [--real <game.toml>]"
shift

suite=""
real_arg=""

case "$cmd" in
    run)
        suite="${1:-}"
        [ -n "$suite" ] || die "usage: qa.sh run <suite|all> [--real <game.toml>]"
        shift
        ;;
    restore)
        ;;
    bench-save)
        step="${1:-}"
        [[ "$step" == start || "$step" == record ]] \
            || die "usage: qa.sh bench-save start|record [--real <game.toml>] [--from <save>]"
        shift
        ;;
    *)
        suite="$cmd"
        cmd="run"
        ;;
esac

extra=()
while [ $# -gt 0 ]; do
    case "$1" in
        case=*)  # just qa <suite> case=NAME: only that case (repeatable)
            extra+=(--case "${1#case=}")
            shift
            ;;
        --case)
            shift
            [ -n "${1:-}" ] || die "--case requires a case name"
            extra+=(--case "$1")
            shift
            ;;
        --no-smoke|no-smoke)
            extra+=(--no-smoke)
            shift
            ;;
        kind=*)  # just qa <suite> kind=instant: instant cases only, no clicks (turn cases skipped)
            extra+=(--kind "${1#kind=}")
            shift
            ;;
        --kind)
            shift
            [ -n "${1:-}" ] || die "--kind requires all or instant"
            extra+=(--kind "$1")
            shift
            ;;
        --from)  # bench-save record: the save to keep
            shift
            [ -n "${1:-}" ] || die "--from requires a save path"
            extra+=(--from "$1")
            shift
            ;;
        --real)
            shift
            real_arg="${1:-}"
            [ -n "$real_arg" ] || die "--real requires a path"
            shift
            ;;
        *)
            real_arg="$1"
            shift
            ;;
    esac
done

real_toml=$(resolve_real_toml "$real_arg")
echo "real game: $real_toml"

# over ssh there's no display, and the run's read-only screen checks (the game's window, Wine's crash
# dialog, EOP's error box) saw nothing (live 11-05: "game window not found"): borrow the desktop's
# shellcheck source=desktop_env.sh
. scripts/desktop_env.sh
if desktop_env_borrow; then
    [ -n "$DESKTOP_ENV_FROM" ] && echo "qa: no display here; using the desktop's (DISPLAY=${DISPLAY:-}, from $DESKTOP_ENV_FROM)"
else
    echo "qa: nobody is logged in to the desktop; the run can't see the game's window or its dialogs" >&2
fi

if [ "$cmd" = "run" ]; then
    exec uv run python -m parley.qa run "$suite" --real "$real_toml" ${extra[@]+"${extra[@]}"}
elif [ "$cmd" = "bench-save" ]; then
    exec uv run python -m parley.qa bench-save "$step" --real "$real_toml" ${extra[@]+"${extra[@]}"}
else
    exec uv run python -m parley.qa restore --real "$real_toml"
fi
