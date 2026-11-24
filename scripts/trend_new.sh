#!/usr/bin/env bash
# trend_new.sh <seen> <now>: the lines of <now> that aren't in <seen>, numbers aside. An alert's numbers
# drift as its averages move, and that isn't a new alert (live 11-06: the same slow ruler woke the
# campaign watch again about ten minutes after it was rearmed). FILENAME, not NR==FNR: an empty <seen> is normal.
set -uo pipefail
awk 'function key(s) { gsub(/[0-9]+(\.[0-9]+)?/, "N", s); return s }
     FILENAME == ARGV[1] { seen[key($0)] = 1; next }
     NF && !(key($0) in seen)' "$1" "$2"
