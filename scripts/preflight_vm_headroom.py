#!/usr/bin/env python3
"""Preflight gate (STANDARDS clean-install-test): refuse to start a VM on this machine without
memory to spare. Live 11-24 an 8 GB test VM, the host's Ollama on CPU and Heretic used up the main machine's
memory and swap; nothing was killed and the whole machine hung until it was reset (13:50-14:05).
A test VM belongs on an expendable machine when one has room, not on the shared server.

Checked: a local `virsh ... start|create`, `virt-install` or `qemu-system-*`. A command sent over
ssh runs on the other machine, and that machine's memory is not ours to read here.
Full swap alone is not refused: pages swapped out hours ago sit there harmlessly; what hung the main machine
was available memory running out. Exit 0 = go; otherwise the reason is printed.
PREFLIGHT_COMMAND holds the command.
"""
from __future__ import annotations

import os
import re
import sys

MIN_AVAILABLE_GIB = 14  # a 6 GB test VM plus 8 GB for everything else that runs here
START = re.compile(r"\bvirsh\b[^;&|\n]*\b(start|create)\b|\bvirt-install\b|\bqemu-system-\w+")


def starts_vm_here(cmd: str) -> bool:
    for part in re.split(r"[;&|\n]+", cmd):
        m = START.search(part)
        if m and not re.search(r"\bssh\b", part[:m.start()]):
            return True
    return False


def available_gib(mem: str) -> float:
    m = re.search(r"^MemAvailable:\s+(\d+) kB", mem, re.M)
    return int(m.group(1)) / 1024 / 1024 if m else 0.0


def problems(cmd: str, mem: str) -> list[str]:
    if not starts_vm_here(cmd):
        return []
    have = available_gib(mem)
    if have < MIN_AVAILABLE_GIB:
        return [f"only {have:.1f} GiB of memory is available (need {MIN_AVAILABLE_GIB})"]
    return []


if __name__ == "__main__":
    with open("/proc/meminfo") as f:
        p = problems(os.environ.get("PREFLIGHT_COMMAND", ""), f.read())
    if p:
        sys.exit("VM start refused: " + "; ".join(p) + ". On 11-24 a test VM here hung the main machine until "
                 "it was reset. Free memory first (Heretic, a CPU-loaded Ollama model) or use another machine.")
