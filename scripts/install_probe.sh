#!/usr/bin/env bash
# Put the Lua probe where EOP (mods/parley) and M2EX autoload scripts.
set -euo pipefail
GAME="${MTW2_GAME_DIR:-$HOME/.steam/steam/steamapps/common/Medieval II Total War}"
src="$(dirname "$0")/../lua/parley_probe.lua"

install_to() {
    local dest="$1"
    mkdir -p "$(dirname "$dest")"
    # the first original is kept: a later run would save the Parley plugin over it
    if [ -f "$dest" ] && ! grep -q "parley probe" "$dest" && [ ! -e "$dest.parley-orig" ]; then
        cp -p "$dest" "$dest.parley-orig"
        echo "existing script saved as $dest.parley-orig"
    fi
    cp "$src" "$dest"
    echo "probe installed: $dest"
}

# where the bridge is (install_bridge.sh): EOP master loads <mod>/eopData/eopScripts, 3.3.1
# youneuoy_Data/plugins/lua, and the master path wins. Live 11-10: the probe went only to
# youneuoy_Data and the game root, the bridge kept loading, and "probe" runs weren't the split
MOD="$GAME/mods/parley"
if [ -d "$MOD/eopData/eopScripts" ]; then
    install_to "$MOD/eopData/eopScripts/luaPluginScript.lua"
elif [ -d "$MOD/youneuoy_Data" ]; then
    install_to "$MOD/youneuoy_Data/plugins/lua/luaPluginScript.lua"
fi
# Newer EOP / M2EX layout (game root)
install_to "$GAME/eopData/eopScripts/luaPluginScript.lua"
find "$GAME" -maxdepth 3 -name parley_probe.log -delete
