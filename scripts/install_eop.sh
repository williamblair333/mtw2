#!/usr/bin/env bash
# Install M2TWEOP (pinned release) as its own mod folder, mods/parley, so the vanilla
# game and M2EX stay untouched. EOP needs the 32-bit Steam medieval2.exe (1.52).
set -euo pipefail

TAG="M2TWEOP-3.3.1"
ASSET="M2TWEOP-3.3.1.zip"
SHA256="e1ac32f2e969b56b56750204b6fe1e6e4d412429c7b72f2bd6d0992ef50b00b9"
GAME="${MTW2_GAME_DIR:-$HOME/.steam/steam/steamapps/common/Medieval II Total War}"
MOD="$GAME/mods/parley"

[ -f "$GAME/medieval2.exe" ] || { echo "no medieval2.exe in $GAME: switch the game to Proton (Windows build) first" >&2; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
gh release download "$TAG" -R EOP-Labs/M2TWEOP-library -p "$ASSET" -D "$work"
echo "$SHA256  $work/$ASSET" | sha256sum -c -

mkdir -p "$MOD/logs"
unzip -q -o "$work/$ASSET" -d "$MOD"
cat > "$MOD/parley.cfg" <<EOF
[features]
mod = mods/parley

[video]
# Launch through Steam (launch-option swap): fullscreen mode switches crash Wine's X11
# driver (xvidmode assertion) under protontricks-launch, but not under Steam's Proton.
# A stretched window breaks mouse mapping, so render at the screen's resolution.
windowed = 0
campaign_resolution = ${PARLEY_RES:-1920 1080}
battle_resolution = ${PARLEY_RES:-1920 1080}

[log]
to = mods/parley/logs/system.log.txt
level = * error
EOF
# M2EX replaces campaign files with versions the vanilla engine can't parse
# ("Expected faction" in descr_strat.txt). Give the mod the vanilla copies, which
# override the game's data/ for EOP only.
# A mod that carries campaign files must also carry the base map (the engine then
# looks only in the mod's data/world/maps/base), so copy both folders, then lay the
# vanilla backups over M2EX's replacements.
vanilla=$(ls -d "$GAME"/.parley-backup/*/ 2>/dev/null | head -1 || true)
if [ -n "$vanilla" ] && [ -d "$vanilla/data" ]; then
    mkdir -p "$MOD/data/world/maps/campaign"
    cp -r "$GAME/data/world/maps/base" "$MOD/data/world/maps/"
    cp -r "$GAME/data/world/maps/campaign/imperial_campaign" "$MOD/data/world/maps/campaign/"
    cp -r "$vanilla/data" "$MOD/"
    echo "vanilla campaign and base map copied into $MOD/data"
fi
echo "EOP $TAG installed in $MOD"
