#!/usr/bin/env bash
# Install the parley bridge into the EOP mod folder (replaces the probe).
set -euo pipefail
GAME="${MTW2_GAME_DIR:-$HOME/.steam/steam/steamapps/common/Medieval II Total War}"
MOD="$GAME/mods/parley"
# EOP master loads <mod>/eopData/eopScripts/luaPluginScript.lua (luaPlugin.cpp:39); 3.3.1 loads
# youneuoy_Data/plugins/lua. A master folder copied from 3.3.1 has both: the master path wins.
dest="$MOD/youneuoy_Data/plugins/lua"
[ -d "$MOD/eopData/eopScripts" ] && dest="$MOD/eopData/eopScripts"
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
python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()[:12])" "$dest/parley_bridge.lua" > "$GAME/parley_turns/parley_build.txt"
# EOP master runs the game from the mod folder, and the bridge opens "parley_turns" relative to
# the working directory (live, 2026-10-25: under master it read and wrote nothing until linked)
[ -e "$MOD/parley_turns" ] || ln -s ../../parley_turns "$MOD/parley_turns"
# the bridge reads what's on screen from the fork's gameSTDUI.getOpenUiElements; the old list of
# UI-like names from the exe (tried one by one) is gone
rm -f "$GAME/parley_turns/ui_names.txt"
echo "bridge installed in $dest; turn files in $GAME/parley_turns"
