"""scripts/pdbsym.py: public symbols from a PDB (a tiny synthetic MSF file and PE header)."""

import importlib.util
import struct
from pathlib import Path

_spec = importlib.util.spec_from_file_location("pdbsym", Path(__file__).parent.parent / "scripts" / "pdbsym.py")
ps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ps)

BS = 512


def _pub(seg: int, off: int, name: str) -> bytes:
    body = struct.pack("<HIIH", ps.S_PUB32, 0, off, seg) + name.encode() + b"\0"
    body += b"\0" * (-(len(body) + 2) % 4)
    return struct.pack("<H", len(body)) + body


def _pdb(streams: list[bytes]) -> bytes:
    # block 0 superblock, block 1 the directory's block map, block 2 the directory, then stream blocks
    blocks, nxt, idx = [], 3, []
    for s in streams:
        k = (len(s) + BS - 1) // BS
        idx.append(list(range(nxt, nxt + k)))
        blocks += [s[i * BS:(i + 1) * BS].ljust(BS, b"\0") for i in range(k)]
        nxt += k
    d = struct.pack("<I", len(streams)) + b"".join(struct.pack("<I", len(s)) for s in streams)
    d += b"".join(struct.pack(f"<{len(i)}I", *i) for i in idx)
    sb = ps.MSF_MAGIC + struct.pack("<6I", BS, 1, nxt, len(d), 0, 1)
    return sb.ljust(BS, b"\0") + struct.pack("<I", 2).ljust(BS, b"\0") + d.ljust(BS, b"\0") + b"".join(blocks)


def _pe(vas: list[int]) -> bytes:
    pe = bytearray(0x200)
    struct.pack_into("<I", pe, 0x3C, 0x80)
    struct.pack_into("<H", pe, 0x80 + 6, len(vas))
    struct.pack_into("<H", pe, 0x80 + 20, 0xE0)
    for k, va in enumerate(vas):
        struct.pack_into("<I", pe, 0x80 + 24 + 0xE0 + 40 * k + 12, va)
    return bytes(pe)


def test_names_an_address_by_the_nearest_public_below_it():
    dbi = bytearray(64)
    struct.pack_into("<H", dbi, 20, 4)  # the symbol record stream is stream 4
    syms = _pub(1, 0x100, "?TextWrapped@ImGui@@YAXPBDZZ") + _pub(1, 0x40, "?Begin@ImGui@@X") + _pub(2, 0, "_data")
    pubs = ps.publics(_pdb([b"", b"", b"", bytes(dbi), syms]), _pe([0x1000, 0x8000]))
    assert pubs == [(0x1040, "?Begin@ImGui@@X"), (0x1100, "?TextWrapped@ImGui@@YAXPBDZZ"), (0x8000, "_data")]
    assert ps.name(pubs, 0x1176) == "?TextWrapped@ImGui@@YAXPBDZZ +0x76"
    assert ps.name(pubs, 0x10) == "?"
