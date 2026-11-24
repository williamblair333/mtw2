"""scripts/ui_classes.py: UI class names from an exe's MSVC RTTI, on a synthetic PE, and the bridge's
K.UI_CLASSES table checked against the real game exe when it's installed."""

import importlib.util
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("ui_classes", ROOT / "scripts" / "ui_classes.py")
uc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uc)

BASE = 0x400000
SECT_ALIGN = 0x1000
# section: (name, rva, raw offset, size); raw == rva - 0x800 keeps the arithmetic plain
TEXT, RDATA, DATA = (".text", 0x1000, 0x400, 0x1000), (".rdata", 0x2000, 0x1400, 0x1000), (".data", 0x3000, 0x2400, 0x1000)


def _va(sect, off):
    return BASE + sect[1] + off


def build_pe() -> tuple[bytes, dict]:
    """A minimal 32-bit PE with two UI classes: each a TypeDescriptor in .data, a CompleteObjectLocator
    and a 3-slot vtable in .rdata, the vtable's functions in .text."""
    img = bytearray(DATA[2] + DATA[3])
    struct.pack_into("<I", img, 0x3C, 0x80)                       # e_lfanew
    img[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", img, 0x84, 0x14C, 3)                   # machine i386, 3 sections
    struct.pack_into("<H", img, 0x84 + 16, 0xE0)                   # SizeOfOptionalHeader
    opt = 0x80 + 24
    struct.pack_into("<I", img, opt + 28, BASE)                    # ImageBase
    sec = opt + 0xE0
    for i, (name, rva, raw, size) in enumerate((TEXT, RDATA, DATA)):
        struct.pack_into("<8sIIII", img, sec + 40 * i, name.encode(), size, rva, size, raw)
    known = {}
    for k, cls in enumerate(("VOTE_BUTTON", "UI_MESSAGE_ICON")):
        td = _va(DATA, 0x100 * k)
        name = f".?AV{cls}@UI@@".encode() + b"\0"
        img[DATA[2] + 0x100 * k + 8: DATA[2] + 0x100 * k + 8 + len(name)] = name
        col = _va(RDATA, 0x200 * k)
        struct.pack_into("<IIII", img, RDATA[2] + 0x200 * k, 0, 0, 0, td)  # signature 0 ... TypeDescriptor
        vt = col + 0x40
        struct.pack_into("<I", img, RDATA[2] + 0x200 * k + 0x3C, col)       # vtable[-1] = the COL
        funcs = [_va(TEXT, 0x400 * k + 0x100 * i) for i in range(3)]
        struct.pack_into("<III", img, RDATA[2] + 0x200 * k + 0x40, *funcs)
        known[cls] = (vt, funcs)
    return bytes(img), known


def test_rtti_names_each_vtable():
    data, known = build_pe()
    exe = uc.Exe(data)
    for cls, (vt, funcs) in known.items():
        assert uc.short(exe.rtti_name(vt)) == cls
        assert exe.vtable(vt) == funcs
    assert exe.rtti_name(known["VOTE_BUTTON"][1][0]) is None  # a function isn't a vtable


def test_the_scan_finds_every_ui_class():
    data, known = build_pe()
    found = {uc.short(c): v for c, v in uc.Exe(data).ui_classes.items()}
    assert found == {cls: [vt] for cls, (vt, _) in known.items()}


def test_a_code_address_maps_to_its_class_method():
    data, known = build_pe()
    exe = uc.Exe(data)
    vt, funcs = known["UI_MESSAGE_ICON"]
    start, owners = exe.method_at(funcs[2] + 0x10)
    assert start == funcs[2] and owners == [("UI_MESSAGE_ICON", 2)]
    assert exe.method_at(BASE) is None  # below every method


def test_readbytes_hex_is_the_little_endian_vtable():
    assert uc.readbytes_hex(0x01393E9C) == "9c3e3901"  # UI::VOTE_BUTTON, as the live bridge reads it


def test_the_cli_names_a_readbytes_string(tmp_path, capsys):
    data, known = build_pe()
    exe_path = tmp_path / "game.exe"
    exe_path.write_bytes(data)
    vt = known["VOTE_BUTTON"][0]
    assert uc.main(["--exe", str(exe_path), "vtable", "--le", uc.readbytes_hex(vt)]) == 0
    assert capsys.readouterr().out.strip().endswith("VOTE_BUTTON")


def test_a_missing_exe_is_an_error(tmp_path, capsys):
    assert uc.main(["--exe", str(tmp_path / "nope.exe"), "classes"]) == 2
    assert "no exe at" in capsys.readouterr().err


def _bridge_ui_classes() -> dict[str, str]:
    text = (ROOT / "lua" / "parley_bridge.lua").read_text(encoding="utf-8")
    block = text[text.index("K.UI_CLASSES = {"):]
    block = block[: block.index("}")]
    return dict(re.findall(r'\["([0-9a-f]{8})"\]\s*=\s*"([A-Z_]+)"', block))


@pytest.mark.skipif(not uc.DEFAULT_EXE.is_file(), reason="the game's exe isn't installed here")
def test_the_bridges_class_table_matches_the_game_exe():
    # 11-20: UNDECIDED_VOTE_BUTTON was entered as dc499401, a mistyped 0x013949dc (dc493901)
    exe = uc.Exe(uc.DEFAULT_EXE.read_bytes())
    table = _bridge_ui_classes()
    assert table, "K.UI_CLASSES not found in lua/parley_bridge.lua"
    for hexstr, cls in table.items():
        vt = struct.unpack("<I", bytes.fromhex(hexstr))[0]
        assert uc.short(exe.rtti_name(vt) or "") == cls, (hexstr, cls)
