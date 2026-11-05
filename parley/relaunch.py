"""The no-click relaunch's file edits (scripts/relaunch_game.sh calls these; docs/superpowers/specs/
2026-10-31-no-click-relaunch.md).

Two settings replace the two clicks of the old relaunch:
- `"hideLauncher": true` in EOP's uiCfg.json starts the mod without the launcher's "Run mod" button.
  The installed launcher reads eopData/config/uiCfg.json, the docs say eopData/uiCfg.json: both are set.
- `bypass_to_strategy_save = mods/parley/saves/<name>.sav` in parley.cfg's [misc] loads that save at
  start-up instead of the main menu (no "Continue Campaign"). Live 10-31 08:37-08:40: the full
  mods/parley/saves/ path loads; a bare name brings up EOP's modal "Cannot create M2TWEOP save file"
  box. The line is written just before a launch and stripped right after, so a later manual launch
  shows the menu instead of loading a stale save.

Stdlib only at import time: install_eop.sh runs `hide-launcher` with the system python3."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BYPASS_KEY = "bypass_to_strategy_save"
SAVES_REL = "mods/parley/saves"
UI_CFG_FILES = ("eopData/config/uiCfg.json", "eopData/uiCfg.json")

_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_BYPASS_RE = re.compile(rf"^\s*{BYPASS_KEY}\s*=")


def _is_section(line: str, name: str | None = None) -> bool:
    m = _SECTION_RE.match(line)
    return bool(m) and (name is None or m.group(1).strip().lower() == name)


def strip_bypass(text: str) -> str:
    """`text` without any bypass_to_strategy_save line; a [misc] section left empty goes too."""
    lines = [ln for ln in text.splitlines() if not _BYPASS_RE.match(ln)]
    out: list[str] = []
    i = 0
    while i < len(lines):
        if _is_section(lines[i], "misc"):
            j = i + 1
            while j < len(lines) and not _is_section(lines[j]):
                j += 1
            if all(not ln.strip() for ln in lines[i + 1:j]):
                i = j  # an empty [misc]: drop it with its blank lines
                continue
        out.append(lines[i])
        i += 1
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + "\n" if out else ""


def set_bypass(text: str, save_rel: str) -> str:
    """`text` with exactly one `bypass_to_strategy_save = <save_rel>`, in [misc] (added if missing)."""
    lines = strip_bypass(text).splitlines()
    entry = f"{BYPASS_KEY} = {save_rel}"
    for i, ln in enumerate(lines):
        if _is_section(ln, "misc"):
            lines.insert(i + 1, entry)
            return "\n".join(lines) + "\n"
    if lines:
        lines.append("")
    lines += ["[misc]", entry]
    return "\n".join(lines) + "\n"


def bypass_value(save_name: str) -> str:
    """The cfg value for a save in mods/parley/saves: always the game-relative path, never a bare
    name (a bare name blocks the game on EOP's ERROR box, live 10-31)."""
    if not save_name or "/" in save_name or "\\" in save_name or save_name.startswith("."):
        raise ValueError(f"not a save file name: {save_name!r}")
    if not save_name.endswith(".sav"):
        raise ValueError(f"not a .sav file: {save_name!r}")
    return f"{SAVES_REL}/{save_name}"


def hide_launcher(mod_dir: Path) -> list[Path]:
    """Set "hideLauncher": true in each uiCfg.json under `mod_dir` that exists; return the files
    that now carry it. Idempotent: a file already set is left untouched. No file at all is an error
    (the launcher would show and wait for a click)."""
    found: list[Path] = []
    for rel in UI_CFG_FILES:
        path = Path(mod_dir) / rel
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: not a JSON object")
        if data.get("hideLauncher") is not True:
            data["hideLauncher"] = True
            path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        found.append(path)
    if not found:
        raise FileNotFoundError(
            f"no {' or '.join(UI_CFG_FILES)} under {mod_dir}: the EOP launcher would wait for a click"
        )
    return found


def choose_save(save_dir: Path, turn_root: Path, explicit: str | None = None) -> str:
    """The save file name to load at start-up.

    - `explicit` (the QA restore passes the keep save): that file, which must exist.
    - After a QA restore (<turn_root>/qa.last_restore) with no real save newer than it recorded: the
      newest parley_keep_*.restored-*.sav (the real campaign; the newest save on disk is the QA game's
      autosave, live 10-30 20:12). This is what `python -m parley.qa after-relaunch` corrected after
      the old Continue Campaign click.
    - Otherwise the newest save the game wrote itself (what Continue Campaign loaded)."""
    from parley.qa.runner import LAST_RESTORE_FILE, newest_real_save

    save_dir = Path(save_dir)
    if explicit:
        bypass_value(explicit)  # a bare file name, a .sav
        if not (save_dir / explicit).is_file():
            raise FileNotFoundError(f"no save {explicit} in {save_dir}")
        return explicit
    newest = newest_real_save(save_dir)
    last_restore = Path(turn_root) / LAST_RESTORE_FILE
    if last_restore.exists():
        try:
            rec = float(json.loads(last_restore.read_text(encoding="utf-8"))["newest_save_mtime"])
        except (OSError, ValueError, TypeError, KeyError) as e:
            raise ValueError(f"invalid {last_restore}: {e}") from e
        if newest is None or newest.stat().st_mtime <= rec:
            restored = sorted(
                (
                    p
                    for p in save_dir.glob("parley_keep_*.restored-*.sav")
                    if not p.name.endswith("-aborted.sav")
                ),
                key=lambda p: (p.stat().st_mtime, p.name),
            )
            if restored:
                return restored[-1].name
    if newest is None:
        raise FileNotFoundError(f"no save to load in {save_dir}")
    return newest.name


RELAUNCH_HOLD_NOTE = "(the game was relaunched while a QA run holds qa.lock; its owner lifts this)"


def hold_for_qa(turn_root: Path) -> str:
    """Before a relaunch: with <turn_root>/qa.lock present, put the turn on hold (paused.txt) so the
    game comes up held. Live 10-31: a relaunch during a QA run loaded the save, and the bridge ended
    the loaded turn right after "bridge loaded campaign", starting every AI turn under the bench. The
    reason starts with the QA runner's hold reason, so the run's owner (the runner's case holds and
    the QA restore, which lifts it once the kept save is loaded) releases it as its own. Without a
    qa.lock nothing is written: the live campaign plays on as before. An existing pause (a seat's
    usage limit, or a QA hold already up) is left as it is.

    Returns "held", "held already" or "no qa.lock"."""
    from parley.qa.runner import LOCK_FILE, QA_HOLD_REASON, pause_path

    turn_root = Path(turn_root)
    if not (turn_root / LOCK_FILE).exists():
        return "no qa.lock"
    p = pause_path(turn_root)
    if p.exists():
        return "held already"
    p.write_text(f"{QA_HOLD_REASON} {RELAUNCH_HOLD_NOTE}\n", encoding="utf-8")
    return "held"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m parley.relaunch", description="no-click relaunch edits")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("choose-save", help="print the save file name to load")
    p.add_argument("--save-dir", type=Path, required=True)
    p.add_argument("--turn-root", type=Path, required=True)
    p.add_argument("--save", default=None, help="this save (a file name in --save-dir)")
    p = sub.add_parser("set-bypass", help="write the start-up save into the cfg's [misc]")
    p.add_argument("cfg", type=Path)
    p.add_argument("save", help="a file name in mods/parley/saves")
    p = sub.add_parser("strip-bypass", help="remove the start-up save from the cfg")
    p.add_argument("cfg", type=Path)
    p = sub.add_parser("hide-launcher", help='set "hideLauncher": true in the mod\'s uiCfg.json files')
    p.add_argument("mod_dir", type=Path)
    p = sub.add_parser("hold-if-qa", help="with a qa.lock, hold the turn (paused.txt) before the launch")
    p.add_argument("--turn-root", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "hold-if-qa":
            print(hold_for_qa(args.turn_root))
        elif args.cmd == "choose-save":
            print(choose_save(args.save_dir, args.turn_root, args.save))
        elif args.cmd == "set-bypass":
            value = bypass_value(args.save)
            # the cfg sits in mods/parley, so its saves/ is what `value` names from the game folder:
            # a save that isn't there would freeze the game on EOP's modal ERROR box at start-up
            save = args.cfg.parent / "saves" / args.save
            if not save.is_file():
                raise FileNotFoundError(f"load refused: no save at {value} ({save})")
            args.cfg.write_text(set_bypass(args.cfg.read_text(encoding="utf-8"), value), encoding="utf-8")
        elif args.cmd == "strip-bypass":
            if args.cfg.exists():
                text = args.cfg.read_text(encoding="utf-8")
                new = strip_bypass(text)
                if new != text:
                    args.cfg.write_text(new, encoding="utf-8")
        elif args.cmd == "hide-launcher":
            for path in hide_launcher(args.mod_dir):
                print(f"hideLauncher on in {path}")
    except (OSError, ValueError) as e:
        print(f"parley.relaunch {args.cmd}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
