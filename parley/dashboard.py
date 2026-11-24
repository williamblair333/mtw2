"""One page on a running campaign: turn and clock, health, crashes, rulers, open gaps (`just dashboard`)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from parley.trends import trends

LOG_TAIL = 5


def _age(path: Path, now: float) -> str:
    try:
        secs = int(now - path.stat().st_mtime)
    except OSError:
        return "missing"
    return f"{secs // 60}m{secs % 60:02d}s ago" if secs >= 60 else f"{secs}s ago"


def _tail(path: Path, n: int) -> list[str]:
    try:
        data = path.read_bytes()[-20000:]
    except OSError:
        return []
    # Wine writes \n under "ab" (W48); \r stripping kept for logs written by older builds
    lines = data.decode("utf-8", "replace").replace("\r\n", "\n").splitlines()
    return [ln for ln in lines if ln.strip()][-n:]


def _turn_section(turn_root: Path, game_id: str, now: float) -> list[str]:
    out = ["## Turn"]
    hb = turn_root / "heartbeat.txt"
    try:
        beat = hb.read_text(encoding="utf-8").strip().replace("\n", " ")
    except OSError:
        beat = "none"
    out.append(f"- heartbeat: {beat} ({_age(hb, now)})")
    # the loop makes turn folders ahead of the game (live 11-05: turn-0099 at heartbeat 94), so the
    # newest folder holding a report is the turn being played
    reports = sorted((turn_root / game_id).glob("turn-*/*/state.json"), key=lambda p: p.parent.parent.name)
    if reports:
        turn_dir = reports[-1].parent.parent
        answered = sorted(p.parent.name for p in turn_dir.glob("*/orders.json"))
        asked = sorted(p.parent.name for p in turn_dir.glob("*/state.json"))
        waiting = [f for f in asked if f not in answered]
        out.append(f"- newest report: {turn_dir.name} ({_age(reports[-1], now)}); answered: "
                   f"{', '.join(answered) or 'none'}; waiting: {', '.join(waiting) or 'none'}")
    else:
        out.append(f"- newest report: none under {turn_root / game_id}")
    log = turn_root / "parley_bridge.log"
    out.append(f"- bridge log ({_age(log, now)}):")
    out += [f"    {ln[:160]}" for ln in _tail(log, LOG_TAIL)]
    return out


def _loop_running(game_id: str) -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", f"parley run .*{re.escape(game_id)}"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def _health_section(turn_root: Path, game_id: str, now: float) -> list[str]:
    out = ["## Health"]
    out.append(f"- turn loop: {'running' if _loop_running(game_id) else 'NOT running'}")
    lock = turn_root / "qa.lock"
    out.append(f"- qa.lock: {'held (' + _age(lock, now) + ')' if lock.exists() else 'free'}")
    paused = turn_root / "paused.txt"
    if paused.exists():
        # why matters: a QA hold, a seat's usage limit and `just stop` each want a different answer
        try:
            why = paused.read_text(encoding="utf-8").strip().splitlines()[0][:120]
        except (OSError, IndexError):
            why = "?"
        out.append(f"- paused: yes ({_age(paused, now)}): {why}")
    else:
        out.append("- paused: no")
    return out


def _crash_section(repo: Path, now: float) -> list[str]:
    out = ["## Crashes (newest 3)"]
    root = repo / "runs" / "crashes"
    dirs = sorted((p for p in root.glob("*") if p.is_dir()), key=lambda p: p.name)[-3:]
    if not dirs:
        return out + ["- none"]
    for d in reversed(dirs):
        # scripts/crash_report.py writes "- game: <id>, turn N" and "- crash-watch saw: <text>"
        found: dict[str, str] = {}
        try:
            for ln in (d / "report.md").read_text(encoding="utf-8").splitlines():
                for key in ("game", "crash-watch saw"):
                    if ln.startswith(f"- {key}:") and key not in found:
                        found[key] = ln.split(":", 1)[1].strip()
        except OSError:
            pass
        why = "; ".join(found[k] for k in ("game", "crash-watch saw") if k in found)
        out.append(f"- {d.name} ({_age(d, now)}){': ' + why[:120] if why else ''}")
    return out


def _unknown_armies(turn_root: Path, game_id: str, faction: str, turns: list[int]) -> int:
    """Refusals for an army id the faction no longer has: on an AI-run faction its own game AI renames
    captains between turns (live 11-05, run 10: France lost 2-4 orders a turn so)."""
    n = 0
    for t in turns:
        d = Path(turn_root) / game_id / f"turn-{t:04d}" / faction
        for name in ("results.json", "rejected.json"):
            try:
                rows = json.loads((d / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            n += sum(1 for r in rows if isinstance(r, dict) and "unknown army" in str(r.get("reason", "")))
    return n


def _rulers_section(turn_root: Path, game_id: str) -> list[str]:
    out = ["## Rulers (last 5 turns)"]
    data = trends(turn_root, game_id, last=5)
    if not data:
        return out + ["- no answered turns"]
    for faction, ft in sorted(data.items()):
        rows = ft.rows
        orders = sum(r["orders"] for r in rows)
        ok = sum(r["applied_ok"] for r in rows)
        refused = sum(r["refused"] for r in rows)
        late = sum(1 for r in rows if r["late"] or r["seat_error"])
        last = rows[-1]
        out.append(f"- {faction}: turns {rows[0]['turn']}-{last['turn']}, {ok}/{orders} orders applied, "
                   f"{refused} refused, {late} late or failed answers, last answer "
                   f"{last['answer_seconds']:.0f}s, {last['towns']} towns, {last['armies']} armies")
        unknown = _unknown_armies(turn_root, game_id, faction, [r["turn"] for r in rows])
        if unknown:
            out.append(f"    {unknown} refused for an army id no longer there (renamed or gone)")
        out += [f"    ALERT {a}" for a in ft.alerts]
    return out


def _standards(repo: Path) -> list[tuple[str, str]]:
    try:
        text = (repo / "STANDARDS.md").read_text(encoding="utf-8")
    except OSError:
        return []
    m = re.search(r"```yaml\n(.*?)\n```", text, re.DOTALL)
    items: list[tuple[str, str]] = []
    in_standards = False
    for ln in (m.group(1) if m else "").splitlines():
        if re.match(r"^\w", ln):
            in_standards = ln.startswith("standards:")
            continue
        if not in_standards:
            continue
        mid = re.match(r"^\s*-\s+id:\s*(\S+)", ln)
        if mid:
            items.append((mid.group(1).strip("'\""), "unknown"))
            continue
        mst = re.match(r"^\s+status:\s*(\S+)", ln)
        if mst and items:
            items[-1] = (items[-1][0], mst.group(1).strip("'\"").lower())
    return items


def _gaps_section(repo: Path) -> list[str]:
    out = ["## Open gaps (STANDARDS.md)"]
    items = _standards(repo)
    if not items:
        return out + ["- no STANDARDS.md"]
    count = {s: sum(1 for _, st in items if st == s) for s in ("done", "partial", "open")}
    out.append(f"- {count['done']} done, {count['partial']} partial, {count['open']} open of {len(items)}")
    for st in ("open", "partial"):
        ids = [i for i, s in items if s == st]
        if ids:
            out.append(f"- {st}: {', '.join(ids)}")
    return out


def dashboard(turn_root: Path, game_id: str, repo: Path = Path("."), now: float | None = None) -> str:
    turn_root = Path(turn_root).expanduser()
    repo = Path(repo)
    now = time.time() if now is None else now
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    parts = [f"# {game_id} — {stamp}"]
    for section in (_turn_section(turn_root, game_id, now), _health_section(turn_root, game_id, now),
                    _crash_section(repo, now), _rulers_section(turn_root, game_id), _gaps_section(repo)):
        parts.append("\n".join(section))
    return "\n\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="One-page campaign status")
    p.add_argument("turn_root", type=Path)
    p.add_argument("game_id")
    p.add_argument("--repo", type=Path, default=Path("."))
    a = p.parse_args(argv)
    print(dashboard(a.turn_root, a.game_id, a.repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
