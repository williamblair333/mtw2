#!/usr/bin/env bash
# usage: probe.sh '<lua returning a value>' [timeout-seconds]
# Runs one Lua line in the running game through the bridge's control file and prints what it
# returns (the bridge logs "control: lua -> <value>"). It runs on whatever campaign is loaded,
# the real one included: a line that changes the game changes it. Helpers in scope besides M:
#   fac(name)        the faction struct by name ("england")
#   char(f, pattern) the first character of faction f whose full name matches pattern
#   at(c)            "x,y" of a character
# Example: just lua 'local r=char(fac("england"),"Robert") return at(r).." mp="..r.movePointsCharacter'
set -euo pipefail
line=${1:?usage: probe.sh '<lua>' [timeout]}
wait_s=${2:-10}
root=${PARLEY_TURN_ROOT:-$HOME/.steam/steam/steamapps/common/Medieval II Total War/parley_turns}
log="$root/parley_bridge.log"
[ -f "$log" ] || { echo "no bridge log at $log (is the game running with the bridge?)" >&2; exit 2; }
# the QA runner owns the control file while a suite runs
# PARLEY_QA_OWNER=1: the QA run itself asks (its hang check), which may pass its own lock
[ -e "$root/qa.lock" ] && [ "${PARLEY_QA_OWNER:-}" != 1 ] && { echo "a QA run holds $root/qa.lock; probe after it" >&2; exit 2; }
case "$line" in *$'\n'*) echo "one line only" >&2; exit 2;; esac
helpers='local function fac(n) for i=0,stratmap.game.getFactionsCount()-1 do local f=stratmap.game.getFaction(i) if f.name==n then return f end end end local function char(f,p) for j=0,f.numOfCharacters-1 do local c=f:getCharacter(j) local r=c.namedCharacter if r and r.fullName and r.fullName:find(p) then return c end end end local function at(c) return math.floor(c.xCoord)..","..math.floor(c.yCoord) end'
start=$(wc -l < "$log")
printf 'lua %s %s\n' "$helpers" "$line" > "$root/control.txt"
for _ in $(seq $((wait_s * 2))); do
    sleep 0.5
    out=$(tail -n +"$((start + 1))" "$log" | awk '/control: lua -> /{sub(/.*control: lua -> /,""); print; exit}')
    if [ -n "$out" ]; then echo "$out"; exit 0; fi
done
echo "no answer in ${wait_s}s (the bridge reads control.txt on its tick; is the game on the campaign map?)" >&2
exit 1
