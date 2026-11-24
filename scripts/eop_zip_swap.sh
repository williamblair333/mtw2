#!/usr/bin/env bash
# Swap the running campaign onto another EOP build (our fork's Gitea zip, 11-15), safely:
#   1. back up mods/parley's DLLs, eopData/config, eopScripts and parley.cfg
#   2. stop crash-watch first (it would relaunch the game mid-install), then pause the campaign
#   3. stop the game, install the zip (sha256-checked), reinstall the bridge (the zip's
#      eopScripts replace its loader), and show how eopData/config changed against the backup
#   4. relaunch on the newest save, resume the campaign, start crash-watch again
# usage: eop_zip_swap.sh <zip> <sha256> [campaign name, default scratch]
# Rollback: copy .parley-backup/eop-before-<sha8>/ back over mods/parley and run this again's
# steps 4 by hand (just relaunch-game; just play <name>; just crash-watch).
set -euo pipefail
cd "$(dirname "$0")/.."
zip="${1:?usage: $0 <zip> <sha256> [name]}"
sha="${2:?usage: $0 <zip> <sha256> [name]}"
name="${3:-scratch}"
game="${MTW2_GAME_DIR:-$HOME/.steam/steam/steamapps/common/Medieval II Total War}"
mod="$game/mods/parley"
just="${PARLEY_JUST:-just}"
echo "$sha  $zip" | sha256sum -c - >/dev/null || { echo "eop-swap: $zip doesn't match $sha" >&2; exit 1; }

backup="$game/.parley-backup/eop-before-${sha:0:8}"
# a second swap to the same build must not back up the new build over the old one
if [ -e "$backup" ]; then backup="$backup-$(date +%Y%m%d%H%M%S)"; fi
mkdir -p "$backup"
cp -a "$mod/"*.dll "$backup/" 2>/dev/null || true
[ -d "$mod/eopData/config" ] && cp -a "$mod/eopData/config" "$backup/config"
[ -d "$mod/eopData/eopScripts" ] && cp -a "$mod/eopData/eopScripts" "$backup/eopScripts"
[ -f "$mod/parley.cfg" ] && cp -a "$mod/parley.cfg" "$backup/"
echo "eop-swap: backup in $backup"

"$just" crash-watch-stop
if pgrep -af "[c]rash_watch.sh" >/dev/null; then echo "eop-swap: crash-watch still running; stopping" >&2; exit 1; fi
"$just" stop
pkill -x medieval2.exe 2>/dev/null || true
for _ in $(seq 1 60); do pgrep -x medieval2.exe >/dev/null || break; sleep 1; done
if pgrep -x medieval2.exe >/dev/null; then echo "eop-swap: the game didn't exit" >&2; exit 1; fi

MTW2_GAME_DIR="$game" EOP_BUILD=zip EOP_ZIP="$zip" EOP_SHA256="$sha" bash scripts/install_eop.sh
"$just" install-bridge
if [ -d "$backup/config" ]; then
    # the fork's zip ships no eopData/config (fork #10) and install_eop.sh rewrites Parley's keys,
    # so this shows only what changed: nothing, or an older zip's files corrected
    echo "eop-swap: eopData/config after the install, against before:"
    diff -r "$backup/config" "$mod/eopData/config" || true
fi

"$just" relaunch-game
"$just" play "$name"
"$just" crash-watch
echo "eop-swap: done; $name resumed on $(basename "$zip") ($sha)"
