"""Name the game's UI classes from medieval2.exe's MSVC RTTI: what a vtable is, which class method holds
a code address, and the vtable bytes a Lua `uiElementStruct:readBytes(0, 4)` returns for a class.

Every UI element starts with its vtable pointer; vtable[-1] points at the MSVC CompleteObjectLocator,
whose TypeDescriptor names the class (".?AVUI_MESSAGE_ICON@UI@@"). On 2026-11-20 this named the
minimized-message icon (UI::UI_MESSAGE_ICON, slot 60 opens it: fork level 6 activate()), the papal vote
buttons (UI::VOTE_BUTTON), and the classes on the 08:36 crash stack (DECIDED_VOTE_BUTTON under
PAPAL_ELECTION_RESULTS_SCROLL). Read-only: it parses the exe file, never the running game.

    python3 scripts/ui_classes.py classes [--match VOTE]     # class, primary vtable, slots, readBytes hex
    python3 scripts/ui_classes.py vtable 0x01363b6c          # the class of a vtable
    python3 scripts/ui_classes.py vtable --le 6c3b3601       # the same, from a readBytes(0, 4) string
    python3 scripts/ui_classes.py addr 0x00b2fb48 0xbf47bc   # the class method each code address is in
"""

from __future__ import annotations

import argparse
import bisect
import struct
import sys
from functools import cached_property
from pathlib import Path

DEFAULT_EXE = Path.home() / ".steam/steam/steamapps/common/Medieval II Total War/medieval2.exe"
UI_NAMESPACE = "@UI@@"


class Exe:
    """A 32-bit PE: sections, little-endian reads at virtual addresses, vtables, RTTI class names."""

    def __init__(self, data: bytes):
        self.d = data
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        n = struct.unpack_from("<H", data, pe + 6)[0]
        opt = struct.unpack_from("<H", data, pe + 20)[0]
        self.base = struct.unpack_from("<I", data, pe + 24 + 28)[0]
        sec = pe + 24 + opt
        self.sections = []
        for i in range(n):
            name, vsize, va, rsize, raw = struct.unpack_from("<8sIIII", data, sec + 40 * i)
            self.sections.append((name.rstrip(b"\0").decode(), self.base + va, vsize, raw, rsize))

    def _off(self, a: int) -> int | None:
        for _, va, vsize, raw, rsize in self.sections:
            if va <= a < va + min(vsize, rsize):
                return a - va + raw
        return None

    def u32(self, a: int | None) -> int | None:
        o = None if a is None else self._off(a)
        return None if o is None or o + 4 > len(self.d) else struct.unpack_from("<I", self.d, o)[0]

    def section(self, a: int | None) -> str | None:
        for name, va, vsize, _, _ in self.sections:
            if a is not None and va <= a < va + vsize:
                return name
        return None

    def cstr(self, a: int) -> str | None:
        o = self._off(a)
        if o is None:
            return None
        end = self.d.find(b"\0", o)
        return self.d[o:end].decode("latin1") if end >= 0 else None

    def vtable(self, a: int, limit: int = 400) -> list[int]:
        """The vtable's function pointers, up to the first entry that isn't code."""
        out = []
        for i in range(limit):
            f = self.u32(a + 4 * i)
            if self.section(f) != ".text":
                break
            out.append(f)
        return out

    def rtti_name(self, vt: int) -> str | None:
        """vtable[-1] -> CompleteObjectLocator (signature 0); +12 -> TypeDescriptor; +8 -> its name."""
        col = self.u32(vt - 4)
        if self.section(col) is None or self.u32(col) != 0:
            return None
        td = self.u32(col + 12)
        return self.cstr(td + 8) if td is not None and self.section(td) else None

    @cached_property
    def ui_classes(self) -> dict[str, list[int]]:
        """Every UI:: class's vtables (a multiply-inherited class has several), found by scanning
        .rdata for a CompleteObjectLocator pointer followed by a code pointer."""
        names: dict[str, list[int]] = {}
        for name, va, vsize, _, _ in self.sections:
            if name != ".rdata":
                continue
            for a in range(va, va + vsize - 8, 4):
                col = self.u32(a)
                if self.section(col) != ".rdata" or self.u32(col) != 0:
                    continue
                if self.section(self.u32(a + 4)) != ".text":
                    continue
                cls = self.rtti_name(a + 4)
                if cls and UI_NAMESPACE in cls:
                    names.setdefault(cls, []).append(a + 4)
        return names

    def primary(self, cls: str) -> int:
        """The class's main vtable: the longest of its vtables."""
        return max(self.ui_classes[cls], key=lambda v: len(self.vtable(v)))

    @cached_property
    def _methods(self) -> tuple[list[int], dict[int, set[tuple[str, int]]]]:
        fn: dict[int, set[tuple[str, int]]] = {}
        for cls, vts in self.ui_classes.items():
            for vt in vts:
                for i, f in enumerate(self.vtable(vt)):
                    fn.setdefault(f, set()).add((short(cls), i))
        return sorted(fn), fn

    def method_at(self, addr: int) -> tuple[int, list[tuple[str, int]]] | None:
        """The nearest UI class method starting at or below addr: (its start, [(class, slot)]).
        A guess for an address inside a non-virtual helper: it names the closest virtual below."""
        starts, fn = self._methods
        j = bisect.bisect_right(starts, addr) - 1
        if j < 0:
            return None
        return starts[j], sorted(fn[starts[j]])


def short(cls: str) -> str:
    return cls.removeprefix(".?AV").removeprefix(".?AU").removesuffix(UI_NAMESPACE)


def readbytes_hex(vt: int) -> str:
    """What `uiElementStruct:readBytes(0, 4)` returns for an element with this vtable."""
    return struct.pack("<I", vt).hex()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classes", help="list UI classes")
    c.add_argument("--match", default="", help="only classes whose name contains this (case-insensitive)")
    v = sub.add_parser("vtable", help="the class of a vtable address")
    v.add_argument("addrs", nargs="+")
    v.add_argument("--le", action="store_true", help="the values are readBytes(0, 4) hex strings")
    a = sub.add_parser("addr", help="the class method holding each code address")
    a.add_argument("addrs", nargs="+")
    args = ap.parse_args(argv)
    if not args.exe.is_file():
        print(f"no exe at {args.exe} (--exe PATH)", file=sys.stderr)
        return 2
    exe = Exe(args.exe.read_bytes())
    if args.cmd == "classes":
        for cls in sorted(exe.ui_classes):
            if args.match.lower() in cls.lower():
                vt = exe.primary(cls)
                print(f"{short(cls)}\tvtable {vt:#010x}\tslots {len(exe.vtable(vt))}\treadBytes {readbytes_hex(vt)}")
    elif args.cmd == "vtable":
        for s in args.addrs:
            vt = struct.unpack("<I", bytes.fromhex(s))[0] if args.le else int(s, 16)
            name = exe.rtti_name(vt)
            print(f"{vt:#010x}\t{short(name) if name else '(no RTTI: not a vtable)'}")
    else:
        for s in args.addrs:
            addr = int(s, 16)
            hit = exe.method_at(addr)
            if hit is None:
                print(f"{addr:#010x}\t(below every UI method)")
            else:
                start, owners = hit
                where = ", ".join(f"{cls} slot {i}" for cls, i in owners[:3])
                print(f"{addr:#010x}\t{start:#010x}+{addr - start:#x}\t{where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
