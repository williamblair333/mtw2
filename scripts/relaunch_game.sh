#!/usr/bin/env bash
# Relaunch the game after a crash and load a save, unattended and with no screen clicks (the author,
# 2026-10-26: "find a way to do that on your own when testing"; 10-31: never click the screen).
# docs/superpowers/specs/2026-10-31-no-click-relaunch.md, proven by hand live 10-31 08:37-08:40:
#   1. pick the save (--save <name>.sav from the QA restore = the keep save; else after a QA restore
#      with no newer real save, the restored keep save; else the newest save the game wrote:
#      parley/relaunch.py choose_save). Nothing is killed when there is no save to load.
#   2. "hideLauncher": true in EOP's uiCfg.json files: no launcher, no "Run mod" click.
#   2b. with a qa.lock (a QA run in progress) the turn is held first (paused.txt, the QA hold's
#      reason): the game comes up held and the run's restore lifts it once its save is loaded.
#   3. stop what is left of the game and Steam's launch chain.
#   4. `bypass_to_strategy_save = mods/parley/saves/<name>.sav` in parley.cfg's [misc]: the game loads
#      it at start-up, no "Continue Campaign" click. Always the mods/parley/saves/ path: a bare name
#      brings up EOP's modal "ERROR: Cannot create M2TWEOP save file. 2" box. The line is stripped
#      on every exit (trap), so a manual launch later shows the menu instead of a stale save.
#   5. `steam steam://rungameid/4700`, then wait (PARLEY_RELAUNCH_TIMEOUT, 240 s; live it took 20 s)
#      for "bridge loaded campaign at turn N" after the pre-launch log size (the main menu's own
#      map logs "main menu map loaded" instead, W47). EOP's ERROR box (read-only `xdotool search`) or the timeout: the
#      game is stopped and this fails. That wait starts once Steam has started the game (the game's
#      process, or the bridge log growing); before that Steam gets PARLEY_STEAM_START_TIMEOUT (900 s):
#      after the test laptop's 03:00 boot (11-10) Steam updated itself and restarted first, and started the
#      game about 5 min after the launch, by which time a flat 240 s had given up.
# No X input on this path, so it runs in a no-click run (PARLEY_NO_X_INPUT=1, parley/xinput.py).
#
# --clicks: the old clicking path (Run mod, Continue Campaign), deleted 11-21; the flag is refused.
#
# Processes are matched by name (pgrep -x), never by command line: `pkill -f medieval2.exe` killed
# an unrelated shell whose command text held that word, and Steam's launch chain.
set -euo pipefail

clicks=0
want_save=""
while [ $# -gt 0 ]; do
    case "$1" in
        --clicks) clicks=1 ;;
        --save) want_save="${2:?--save needs a save file name}"; shift ;;
        --save=*) want_save="${1#--save=}" ;;
        *) echo "usage: relaunch_game.sh [--save <name>.sav] [--clicks]" >&2; exit 2 ;;
    esac
    shift
done

# the clicking path was deleted 11-21: Parley makes no screen input (parley/xinput.py)
if [ "$clicks" = 1 ]; then
    echo "X input refused in a no-click run: relaunch_game.sh --clicks (the clicking path was deleted 11-21; Parley makes no screen input)" >&2
    exit 3
fi

repo=$(cd "$(dirname "$0")/.." && pwd)
turn_root="${PARLEY_TURN_ROOT:-$HOME/.steam/steam/steamapps/common/Medieval II Total War/parley_turns}"
game_dir="${MTW2_GAME_DIR:-$(dirname "$turn_root")}"
mod="$game_dir/mods/parley"
cfg="$mod/parley.cfg"
log="$turn_root/parley_bridge.log"
py="${PARLEY_PY:-$repo/.venv/bin/python}"
wait_s="${PARLEY_RELAUNCH_TIMEOUT:-240}"
steam_wait_s="${PARLEY_STEAM_START_TIMEOUT:-900}"

relaunch_py() {  # the file edits and the save choice (parley/relaunch.py)
    (cd "$repo" && "$py" -m parley.relaunch "$@")
}

hold_if_qa() {  # with a qa.lock the game comes up held (paused.txt); its run lifts the hold
    # live 10-31: a relaunch during a QA run, unheld, had the bridge end the loaded turn right after
    # "bridge loaded campaign". Without a qa.lock nothing is written: the live campaign plays on
    local held
    [ -e "$turn_root/qa.lock" ] || return 0
    held=$(relaunch_py hold-if-qa --turn-root "$turn_root") \
        || { echo "relaunch: can't hold the turn for the QA run in progress; nothing stopped" >&2; exit 1; }
    [ "$held" = "no qa.lock" ] || echo "relaunch: qa.lock present: the turn is held ($held) until the QA run lifts it"
}

steam_launch_chain() {  # pids of Steam's reaper for this game (SteamLaunch AppId=4700)
    local p
    for p in $(pgrep -x reaper || true); do
        tr '\0' '\n' <"/proc/$p/cmdline" 2>/dev/null | grep -qx 'AppId=4700' && echo "$p"
    done
    return 0
}

stop_game() {  # the game, EOP's launcher and Steam's launch chain for the game
    pkill -x 'medieval2.exe' || true
    pkill -x 'M2TWEOP GUI.exe' || true
    for _ in $(seq 1 30); do pgrep -x 'medieval2.exe' >/dev/null || break; sleep 1; done
    sleep 5  # the launch chain winds down
    # Steam counts the game as running while its reaper lives, and ignores rungameid
    local chain
    chain=$(steam_launch_chain)
    if [ -n "$chain" ]; then
        echo "relaunch: stopping Steam's launch chain ($chain)"
        # shellcheck disable=SC2086  # one pid per word
        kill $chain || true
        sleep 5
    fi
}

stop_crashed_game() {
    if pgrep -x 'medieval2.exe' >/dev/null || pgrep -x 'M2TWEOP GUI.exe' >/dev/null; then
        echo "relaunch: stopping the crashed game"
        stop_game
    fi
}

# The Steam URL that starts the game. `steam://rungameid/4700` answers Steam's "which launch option?"
# with the choice Steam has saved (the main machine, 11-04: "continues with user response \"0\""). A Steam that
# never saved one waits on the dialog (the test laptop, 11-04: "waiting for user response to
# ShowLaunchOption"): set PARLEY_STEAM_URL=steam://launch/4700/option0 there (~/.config/environment.d/,
# so crash-watch's user unit sees it too), which picks the option with no dialog. A shell over ssh
# doesn't read environment.d (the test laptop 11-05: the restore went to rungameid and the dialog), so the
# file is read here when the variable is unset.
env_d="$HOME/.config/environment.d/parley.conf"
if [ -z "${PARLEY_STEAM_URL:-}" ] && [ -f "$env_d" ]; then
    PARLEY_STEAM_URL=$(sed -n 's/^[[:space:]]*PARLEY_STEAM_URL[[:space:]]*=[[:space:]]*//p' "$env_d" \
        | tail -1 | tr -d "\"'")
fi
STEAM_URL="${PARLEY_STEAM_URL:-steam://rungameid/4700}"

# Over ssh, or in a user unit on a desktop that doesn't export DISPLAY to systemd (KDE on the test laptop,
# 11-05), there is no display: a Steam that isn't running yet can't start, and the relaunch times out.
# Take DISPLAY and friends from this user's running desktop shell (scripts/desktop_env.sh).
# shellcheck source=desktop_env.sh
. "$(dirname "$0")/desktop_env.sh"
borrow_desktop_env() {
    if ! desktop_env_borrow; then
        pgrep -u "$(id -u)" -x steam >/dev/null && return 0  # a running Steam takes the URL anyway
        # the test laptop 11-05: after its nightly power-off it waits at the login screen; nothing can start
        echo "relaunch: nobody is logged in to the desktop (no DISPLAY, no desktop shell, no Steam); log in on the machine first" >&2
        exit 1
    fi
    [ -n "$DESKTOP_ENV_FROM" ] && echo "relaunch: no display here; using the desktop's (DISPLAY=${DISPLAY:-} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}, from $DESKTOP_ENV_FROM)"
    return 0
}

start_steam() {
    borrow_desktop_env
    echo "relaunch: starting the game through Steam ($STEAM_URL)"
    if [ "${PARLEY_STEAM_SCOPE:-}" = 1 ]; then
        # under the parley-crash-watch unit (crash_watch_unit.sh): a Steam started here would sit in
        # the unit's cgroup and die when crash-watch is stopped, taking the game with it
        systemd-run --user --scope --collect --quiet steam "$STEAM_URL" >/dev/null 2>&1 &
    else
        # its own session: a Steam started from an ssh shell would die with that shell's hangup
        setsid -f steam "$STEAM_URL" >/dev/null 2>&1 </dev/null
    fi
}

# ---------------------------------------------------------------- the no-click path

# A locked desktop stalls the game behind the lock screen before it sets up graphics, and the wait
# below then fails four minutes later as "no campaign loaded" (the test laptop, 11-04: three launches
# failed until `loginctl unlock-session`; unlocked, the campaign loaded in 23 s). Refuse at once
# instead. Only an explicit "yes" refuses: no loginctl or no graphical session passes.
# PARLEY_IGNORE_LOCK=1 skips the check.
locked_session() {
    command -v loginctl >/dev/null 2>&1 || return 1
    local s
    for s in $(loginctl list-sessions --no-legend 2>/dev/null | awk -v u="$(id -un)" '$3 == u {print $1}'); do
        case "$(loginctl show-session "$s" -p Type --value 2>/dev/null)" in
            x11|wayland)
                if [ "$(loginctl show-session "$s" -p LockedHint --value 2>/dev/null)" = yes ]; then
                    echo "$s"
                    return 0
                fi ;;
        esac
    done
    return 1
}
if [ "${PARLEY_IGNORE_LOCK:-}" != 1 ] && s=$(locked_session); then
    echo "relaunch: the desktop session ($s) is locked; the game stalls behind the lock screen." >&2
    echo "relaunch: unlock it (loginctl unlock-session $s) or turn auto-lock off; nothing stopped" >&2
    exit 1
fi

# both before anything is killed: a failure here leaves the game as it is
save=$(relaunch_py choose-save --save-dir "$mod/saves" --turn-root "$turn_root" ${want_save:+--save "$want_save"}) \
    || { echo "relaunch: no save to load; nothing stopped" >&2; exit 1; }
relaunch_py hide-launcher "$mod" >/dev/null \
    || { echo "relaunch: can't hide EOP's launcher (it would wait for a Run mod click); nothing stopped" >&2; exit 1; }
hold_if_qa

stop_crashed_game

strip_bypass() {
    relaunch_py strip-bypass "$cfg" \
        || echo "relaunch: could not strip bypass_to_strategy_save from $cfg: remove it by hand" >&2
}
trap strip_bypass EXIT
relaunch_py set-bypass "$cfg" "$save"
echo "relaunch: loading $save at start-up"
# A size cap on the bridge log (STANDARDS log-rotation; 11-05 it was 25-26 MB and growing): with the
# game stopped (nothing writes) and no QA run reading it by offset (qa.lock), an oversized log is kept
# as .log.1 (one generation) and the bridge starts a new one. The wait below reads a fresh log whole.
log_cap_mb="${PARLEY_LOG_CAP_MB:-20}"
if [ ! -e "$turn_root/qa.lock" ] && [ "$(stat -c %s "$log" 2>/dev/null || echo 0)" -gt $((log_cap_mb * 1024 * 1024)) ]; then
    mv -f "$log" "$log.1" && echo "relaunch: the bridge log was over ${log_cap_mb} MB: kept as $(basename "$log").1; a new one starts"
fi
log_offset=$(stat -c %s "$log" 2>/dev/null || echo 0)  # only map loads after it are this launch's
start_steam

turn=""
started=""  # the second Steam started the game; the load wait counts from there
# the game seen running, then how many polls in a row it has been gone: tc 11-19 13:30 it reached the
# main menu map, hit "unspecified error and will now exit" while loading, and the wait ran out its
# whole 240 s for a game that was gone. 15 polls, so a blip in Proton's process list isn't an exit.
seen_game=""
gone=0
for i in $(seq 1 $((steam_wait_s + wait_s))); do
    if pgrep -x 'medieval2.exe' >/dev/null; then
        seen_game=1
        gone=0
    elif [ -n "$seen_game" ]; then
        gone=$((gone + 1))
        if [ "$gone" -ge 15 ]; then
            echo "relaunch: the game exited while loading $save (no medieval2.exe for $gone s); stopping what is left" >&2
            stop_game
            exit 1
        fi
    fi
    size=$(stat -c %s "$log" 2>/dev/null || echo 0)
    [ "$size" -lt "$log_offset" ] && log_offset=0  # the log started over: read all of it
    if [ -z "$started" ]; then
        if pgrep -x 'medieval2.exe' >/dev/null || [ "$size" -gt "$log_offset" ]; then
            started=$i
            [ "$i" -gt 60 ] && echo "relaunch: Steam took about $i s to start the game (an update?)"
        elif [ "$i" -gt "$steam_wait_s" ]; then
            break
        fi
    elif [ $((i - started)) -ge "$wait_s" ]; then
        break
    fi
    turn=$(tail -c +"$((log_offset + 1))" "$log" 2>/dev/null \
        | grep -oE 'bridge (reloaded|loaded campaign) at turn [0-9]+' \
        | grep -oE '[0-9]+$' | head -1 || true)
    [ -n "$turn" ] && break
    # EOP's modal box ("Cannot create M2TWEOP save file", "non-EOP save") blocks until clicked
    if xdotool search --name '^ERROR$' >/dev/null 2>&1; then
        echo "relaunch: EOP's ERROR box is up while loading $save; stopping the game" >&2
        stop_game
        exit 1
    fi
    sleep 1
done
if [ -z "$turn" ] && [ -z "$started" ]; then
    echo "relaunch: Steam didn't start the game within ${steam_wait_s} s ($save; its logs: ~/.steam/steam/logs/bootstrap_log.txt, content_log.txt); stopping it" >&2
    stop_game
    exit 1
fi
if [ -z "$turn" ]; then
    echo "relaunch: no 'bridge loaded campaign at turn N' in $log within ${wait_s} s ($save); stopping the game" >&2
    stop_game
    exit 1
fi
echo "relaunch: campaign loaded at turn $turn from $save (no clicks)"
