#!/usr/bin/env bash
# on <name>: resume campaign <name> at every desktop login (scripts/boot_resume.sh, from
# ~/.config/autostart; log logs/boot-resume.log). off: stop doing that.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
resume_file="${PARLEY_RESUME_FILE:-$HOME/.config/parley/resume}"
autostart="${PARLEY_AUTOSTART_DIR:-$HOME/.config/autostart}/parley-resume.desktop"
case "${1:-}" in
    on)
        name="${2:?usage: $0 on <campaign name>}"
        mkdir -p "$(dirname "$resume_file")" "$(dirname "$autostart")" "$repo/logs"
        echo "$name" > "$resume_file"
        cat > "$autostart" <<EOF
[Desktop Entry]
Type=Application
Name=Parley: resume the campaign
Exec=bash "$repo/scripts/boot_resume.sh" --log
X-GNOME-Autostart-enabled=true
NoDisplay=true
EOF
        echo "at each login: resume '$name' ($autostart; log $repo/logs/boot-resume.log)"
        ;;
    off)
        rm -f "$autostart" "$resume_file"
        echo "no campaign resumes at login"
        ;;
    *)
        echo "usage: $0 on <name> | off" >&2
        exit 2
        ;;
esac
