#!/usr/bin/env bash
# Put the Lua probe where EOP (mods/parley) and M2EX autoload scripts.
set -euo pipefail
GAME="${MTW2_GAME_DIR:-$HOME/.steam/steam/steamapps/common/Medieval II Total War}"
src="$(dirname "$0")/../lua/parley_probe.lua"

install_to() {
    local dest="$1"
    mkdir -p "$(dirname "$dest")"
    if [ -f "$dest" ] && ! grep -q "parley probe" "$dest"; then
        cp -p "$dest" "$dest.parley-orig"
        echo "existing script saved as $dest.parley-orig"
    fi
    cp "$src" "$dest"
    echo "probe installed: $dest"
}

# EOP 3.3.1 layout (mod folder)
if [ -d "$GAME/mods/parley/youneuoy_Data" ]; then
    install_to "$GAME/mods/parley/youneuoy_Data/plugins/lua/luaPluginScript.lua"
fi
# Newer EOP / M2EX layout (game root)
install_to "$GAME/eopData/eopScripts/luaPluginScript.lua"
find "$GAME" -maxdepth 3 -name parley_probe.log -delete
