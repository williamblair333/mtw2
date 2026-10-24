#!/usr/bin/env bash
# Install M2EX (pinned release) into the Steam Medieval II folder.
# Backs up every file it would overwrite to $GAME/.parley-backup/<timestamp>/.
set -euo pipefail

TAG="17/08"
ASSET="M2EX.7z"
SHA256="baf03847ccfb7c7950b5b5e71ee3e96329479db46881430f664ad5eb8cedfb31"
GAME="${MTW2_GAME_DIR:-$HOME/.steam/steam/steamapps/common/Medieval II Total War}"

[ -f "$GAME/medieval2.exe" ] || { echo "no medieval2.exe in $GAME: switch the game to Proton (Windows build) first" >&2; exit 1; }
command -v 7z >/dev/null || { echo "7z not found (install p7zip-full)" >&2; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
gh release download "$TAG" -R Pannoniae/rex -p "$ASSET" -D "$work"
echo "$SHA256  $work/$ASSET" | sha256sum -c -

backup="$GAME/.parley-backup/$(date +%Y%m%d-%H%M%S)"
7z l -slt "$work/$ASSET" | sed -n 's/^Path = //p' | tail -n +2 | while IFS= read -r p; do
    if [ -f "$GAME/$p" ]; then
        mkdir -p "$backup/$(dirname "$p")"
        cp -p "$GAME/$p" "$backup/$p"
        echo "backed up: $p"
    fi
done

7z x -y -o"$GAME" "$work/$ASSET" >/dev/null
echo "M2EX $TAG installed in $GAME"
[ -d "$backup" ] && echo "replaced files saved in $backup"
