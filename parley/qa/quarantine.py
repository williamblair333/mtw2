"""Quarantined QA cases (STANDARDS flaky-quarantine): a flaky case still runs and is reported, but its
failure doesn't make the run fail; its cause is tracked in games/quarantine.toml until it's fixed."""

from __future__ import annotations

import tomllib
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent.parent.parent / "games" / "quarantine.toml"


def load(path: Path = DEFAULT) -> dict[str, str]:
    """Case name -> why it's quarantined (and since when); {} when the file is missing or empty."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    cases = data.get("cases") or {}
    return {str(k): str(v) for k, v in cases.items()}


def split_failures(results, quarantined: dict[str, str]) -> tuple[list, list]:
    """(failures that fail the run, failures of quarantined cases)."""
    failed = [r for r in results if r.outcome == "fail"]
    return [r for r in failed if r.name not in quarantined], [r for r in failed if r.name in quarantined]
