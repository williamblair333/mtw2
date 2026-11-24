#!/usr/bin/env python3
"""Name addresses in a DLL from its PDB's public symbols (S_PUB32): the nearest symbol at or below each.

    pdbsym.py M2TWEOPLibrary.pdb M2TWEOPLibrary.dll 0x871c6 M2TWEOPLibrary.dll+0x875d7 ...

Names come out MSVC-mangled (?TextWrapped@ImGui@@YAXPBDZZ: ImGui::TextWrapped); c++filt can't demangle them.

Addresses are RVAs (module offsets), as a crash report's fault-stack.txt prints them
("M2TWEOPLibrary.dll+0x871c6"). Standard library only: neither the test laptop nor the main machine has llvm-pdbutil.
11-13: named the turn 705 crash's stack (sol -> ImGui::TextWrapped -> ImFormatStringToTempBufferV).
EOP's pdb ships in mods/parley next to its dll.
"""

from __future__ import annotations

import bisect
import struct
import sys

MSF_MAGIC = b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0"
S_PUB32 = 0x110E


def _streams(pdb: bytes) -> list[bytes]:
    if not pdb.startswith(MSF_MAGIC):
        raise ValueError("not an MSF 7.00 PDB")
    bs, _, _, dir_bytes, _, map_addr = struct.unpack_from("<6I", pdb, 32)

    def read(idxs, size):
        return b"".join(pdb[i * bs:(i + 1) * bs] for i in idxs)[:size]

    n_map = (dir_bytes + bs - 1) // bs
    d = read(struct.unpack_from(f"<{n_map}I", pdb, map_addr * bs), dir_bytes)
    n = struct.unpack_from("<I", d, 0)[0]
    sizes = [0 if s == 0xFFFFFFFF else s for s in struct.unpack_from(f"<{n}I", d, 4)]
    pos, out = 4 + 4 * n, []
    for s in sizes:
        k = (s + bs - 1) // bs
        out.append(read(struct.unpack_from(f"<{k}I", d, pos), s))
        pos += 4 * k
    return out


def _section_vas(pe: bytes) -> list[int]:
    off = struct.unpack_from("<I", pe, 0x3C)[0]
    nsec = struct.unpack_from("<H", pe, off + 6)[0]
    first = off + 24 + struct.unpack_from("<H", pe, off + 20)[0]
    return [struct.unpack_from("<I", pe, first + 40 * k + 12)[0] for k in range(nsec)]


def publics(pdb: bytes, pe: bytes) -> list[tuple[int, str]]:
    """(rva, mangled name) of every public symbol, sorted."""
    streams = _streams(pdb)
    syms = streams[struct.unpack_from("<H", streams[3], 20)[0]]  # DBI header: the symbol record stream
    vas = _section_vas(pe)
    found, p = [], 0
    while p + 4 <= len(syms):
        ln, kind = struct.unpack_from("<HH", syms, p)
        if ln < 2:
            break
        if kind == S_PUB32:
            _, off, seg = struct.unpack_from("<IIH", syms, p + 4)
            end = syms.index(b"\0", p + 14)
            if 1 <= seg <= len(vas):
                found.append((vas[seg - 1] + off, syms[p + 14:end].decode("latin-1")))
        p += ln + 2
    return sorted(found)


def name(pubs: list[tuple[int, str]], rva: int) -> str:
    i = bisect.bisect_right([a for a, _ in pubs], rva) - 1
    return f"{pubs[i][1]} +{rva - pubs[i][0]:#x}" if i >= 0 else "?"


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    pubs = publics(open(argv[0], "rb").read(), open(argv[1], "rb").read())
    for a in argv[2:]:
        rva = int(a.rsplit("+", 1)[-1], 16)
        print(f"{rva:#x}: {name(pubs, rva)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
