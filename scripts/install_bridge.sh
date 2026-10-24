#!/usr/bin/env bash
# Install the parley bridge into the EOP mod folder (replaces the probe).
set -euo pipefail
GAME="${MTW2_GAME_DIR:-$HOME/.steam/steam/steamapps/common/Medieval II Total War}"
dest="$GAME/mods/parley/youneuoy_Data/plugins/lua"
src="$(cd "$(dirname "$0")/../lua" && pwd)"

[ -d "$dest" ] || { echo "EOP not installed: run just install-eop first" >&2; exit 1; }
if ps -eo args | grep -i "[m]edieval2.exe" | grep -vq "grep\|bash"; then
    echo "note: the game is running; the bridge loads on its next start" >&2
fi
if [ -f "$dest/luaPluginScript.lua" ] && ! grep -q "parley" "$dest/luaPluginScript.lua"; then
    cp -p "$dest/luaPluginScript.lua" "$dest/luaPluginScript.lua.parley-orig"
fi
cp "$src/luaPluginScript.lua" "$src/parley_bridge.lua" "$src/vendor/json.lua" "$dest/"
mkdir -p "$GAME/parley_turns"
echo "bridge installed in $dest; turn files in $GAME/parley_turns"
