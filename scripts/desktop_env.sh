# Sourced, not run. Over ssh, or in a user unit on a desktop that doesn't export DISPLAY to systemd
# (KDE on the test laptop, 11-05), there is no display: Steam can't start and every read-only X
# check (the game's window, Wine's crash dialog, EOP's error box) sees nothing. desktop_env_borrow
# takes DISPLAY and friends from this user's running desktop shell.
# Returns 0 when a display is set (already, or borrowed; DESKTOP_ENV_FROM then says from where),
# 1 when nobody is logged in to a desktop.
desktop_env_borrow() {
    DESKTOP_ENV_FROM=""
    [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && return 0
    local p="" n var val
    for n in plasmashell kwin_x11 kwin_wayland gnome-shell xfce4-session; do
        p=$(pgrep -u "$(id -u)" -x "$n" | head -1 || true)
        [ -n "$p" ] && break
    done
    [ -n "$p" ] || return 1
    for var in DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR; do
        [ -n "${!var:-}" ] && continue
        val=$(tr '\0' '\n' <"/proc/$p/environ" 2>/dev/null | sed -n "s/^$var=//p" | head -1 || true)
        [ -n "$val" ] && export "$var=$val"
    done
    DESKTOP_ENV_FROM="$n pid $p"
    return 0
}
