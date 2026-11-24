"""Change one seat setting in a live game config: `just seat-set <game> <faction> <key> <value>`.

Live 11-23 a hand-typed cp to turn on France's lookups broke on a line wrap, and its rerun
overwrote the only backup. This keeps a fresh timestamped backup every run, edits one line (so
comments stay), checks the result loads, and puts the old file back if it doesn't."""

import os
import re
import sys
import time
import tomllib
from pathlib import Path

from parley.config import SeatConfig, load_config


class SeatSetError(Exception):
    pass


def set_seat_option(path: Path, faction: str, key: str, value: str) -> Path:
    """Set `key = value` (a TOML literal) under [seats.<faction>]; returns the backup's path."""
    path = Path(path)
    if key not in SeatConfig.model_fields:
        raise SeatSetError(f"{key!r} is not a seat setting (known: {', '.join(sorted(SeatConfig.model_fields))})")
    try:
        tomllib.loads(f"v = {value}")
    except tomllib.TOMLDecodeError as e:
        raise SeatSetError(f"{value!r} is not a TOML value (strings need quotes): {e}") from e
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    head = f"[seats.{faction}]"
    try:
        start = next(i for i, x in enumerate(lines) if x.strip() == head)
    except StopIteration:
        raise SeatSetError(f"no {head} in {path}") from None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    new = f"{key} = {value}\n"
    hit = next((i for i in range(start + 1, end) if re.match(rf"\s*{re.escape(key)}\s*=", lines[i])), None)
    if hit is not None:
        old = lines[hit].rstrip("\n")
        lines[hit] = new
    else:
        last = max((i for i in range(start + 1, end) if lines[i].strip() and not lines[i].lstrip().startswith("#")),
                   default=start)
        if not lines[last].endswith("\n"):
            lines[last] += "\n"
        lines.insert(last + 1, new)
        old = "(not set)"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    n = 1
    while backup.exists():  # two runs in one second still keep two backups
        backup = path.with_name(f"{path.name}.bak-{stamp}-{n}")
        n += 1
    backup.write_text(original, encoding="utf-8")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(lines), encoding="utf-8")
    os.replace(tmp, path)
    try:
        load_config(path)
    except Exception as e:
        path.write_text(original, encoding="utf-8")  # the backup stays as a record of the attempt
        raise SeatSetError(f"the config would not load with {key} = {value}, so it is unchanged: {e}") from e
    print(f"{path} [seats.{faction}] {old} -> {new.strip()} (backup: {backup})")
    return backup


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 4:
        print("usage: python -m parley.seat_set <config.toml> <faction> <key> <value>", file=sys.stderr)
        return 2
    try:
        set_seat_option(Path(args[0]), args[1], args[2], args[3])
    except (SeatSetError, OSError) as e:
        print(f"seat-set: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
