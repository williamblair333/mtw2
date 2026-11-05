"""Lessons a persona carries across games: written by a review of its own play every few turns,
recalled in its later prompts, vetoed by the author.

Usage: python -m parley.lessons <game .toml or lessons dir> [veto <id>]"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError


class Lesson(BaseModel):
    id: str
    text: str
    evidence: str = ""
    game_id: str = ""
    turn: int = 0
    version: str = ""  # the code's git short sha when it was learned: lessons from bugs show up
    vetoed: bool = False
    created: str = ""


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def key_for(name: str) -> str:
    """A file-safe key from a persona's display name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "unnamed"


def load(root: Path, key: str) -> list[Lesson]:
    """The persona's lessons; [] when missing or unreadable, invalid items skipped."""
    try:
        raw = json.loads((root / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    lessons = []
    for item in raw:
        if isinstance(item, dict):
            try:
                lessons.append(Lesson.model_validate(item))
            except ValidationError:
                continue
    return lessons


def save(root: Path, key: str, lessons: list[Lesson]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=root, prefix=f".{key}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps([x.model_dump() for x in lessons], indent=2))
        os.replace(tmp, root / f"{key}.json")
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def add(root: Path, key: str, items: list[dict[str, Any]], *, game_id: str, turn: int, version: str,
        today: str) -> list[Lesson]:
    """Keep the new lessons; a text already stored (vetoed ones too) is never added again."""
    lessons = load(root, key)
    seen = {_normalize(x.text) for x in lessons}
    added = []
    for item in items:
        text = item.get("text") if isinstance(item, dict) else None
        if not isinstance(text, str) or not text.strip() or _normalize(text) in seen:
            continue
        evidence = item.get("evidence", "")
        norm = _normalize(text)
        lesson = Lesson(id=hashlib.sha1(f"{key}|{norm}".encode()).hexdigest()[:8], text=text.strip(),
                        evidence=evidence.strip() if isinstance(evidence, str) else "",
                        game_id=game_id, turn=turn, version=version, created=today)
        seen.add(norm)
        lessons.append(lesson)
        added.append(lesson)
    save(root, key, lessons)
    return added


def active(root: Path, key: str, limit: int = 5) -> list[Lesson]:
    """Lessons not vetoed, newest first."""
    return [x for x in reversed(load(root, key)) if not x.vetoed][:max(0, limit)]


def veto(root: Path, lesson_id: str) -> Lesson | None:
    for path in sorted(root.glob("*.json")) if root.is_dir() else []:
        lessons = load(root, path.stem)
        for x in lessons:
            if x.id == lesson_id:
                x.vetoed = True
                save(root, path.stem, lessons)
                return x
    return None


_WHO = {"slave": "rebels"}
_KEY_WORDS = re.compile(r"revolt|rebel|siege|battle|assassin|captur|lost|destroy|excommunic|war\b|alliance|treaty|"
                        r"famine|plague|earthquake", re.I)
_DISASTER = re.compile(r"^.+? was struck by a disaster: (\w+) \(in (\S+)\)$")
OUTCOMES_MAX = 1500
_MAX_EVENTS = 8


def _who(faction: str | None) -> str:
    return _WHO.get(faction or "", faction or "someone")


def _holder(states: list[tuple[int, Any]], sid: str) -> str | None:
    """Who holds a settlement we no longer have, per the latest report that shows it."""
    for _, rep in reversed(states):
        for s in list(rep.nearby_settlements) + list(rep.remembered):
            if s.id == sid:
                return s.faction
    return None


def _events(states: list[tuple[int, Any]], names: set[str], faction: str) -> list[str]:
    """Events the reports carry (stance changes, news, character events, agent results), deduped; the
    same disaster in one region folds into one line; the ones about us or a war come first."""
    seen: set[str] = set()
    disasters: dict[tuple[str, str], list[int]] = {}
    rows: list[tuple[int, int, str]] = []  # (priority, turn, text)
    for t, rep in states:
        for src in (rep.stance_changes, rep.news, rep.character_events, rep.agent_results):
            for text in src:
                m = _DISASTER.match(text)
                if m:
                    disasters.setdefault((m.group(1), m.group(2)), []).append(t)
                    continue
                if text in seen:
                    continue
                seen.add(text)
                hot = faction in text.lower() or any(n in text for n in names) or _KEY_WORDS.search(text)
                rows.append((0 if hot else 1, t, f"T{t}: {text[:110]}"))
    for (kind, region), turns in disasters.items():
        span = f"T{turns[0]}" if turns[0] == turns[-1] else f"T{turns[0]}-{turns[-1]}"
        rows.append((0, turns[0], f"{span}: {kind} in {region}"))
    rows.sort()
    kept = sorted(rows[:_MAX_EVENTS], key=lambda r: (r[1], r[0]))
    out = [r[2] for r in kept]
    if len(rows) > _MAX_EVENTS:
        out.append(f"(+{len(rows) - _MAX_EVENTS} minor events)")
    return out


def _order_line(sid: str, states: list[tuple[int, Any]], kept: bool) -> str | None:
    seen = [(t, s) for t, rep in states for s in rep.settlements if s.id == sid]
    (ta, a), (tb, b) = seen[0], seen[-1]
    if a.public_order is None and b.public_order is None:
        return None

    def fmt(s) -> str:
        return f"{s.public_order}% order, tax {s.tax_level or '?'}"

    txt = f"{a.name}: T{ta} {fmt(a)} -> T{tb} {fmt(b)}"
    ordered = [x for x in seen if x[1].public_order is not None]
    low = min(ordered, key=lambda x: x[1].public_order)
    if low[1].public_order < min(a.public_order or 999, b.public_order or 999):
        txt += f"; low {low[1].public_order}% T{low[0]}"
    taxes, prev = [], a.tax_level
    for t, s in seen[1:]:
        if s.tax_level != prev:
            taxes.append(f"{prev}->{s.tax_level} T{t}")
        prev = s.tax_level
    if taxes:
        txt += f"; tax changed {', '.join(taxes[:3])}"
    if not kept:
        txt += f"; last held T{tb}"
    return txt


def outcomes_section(states: list[tuple[int, Any]]) -> str:
    """What happened to this faction over the reviewed stretch, from its own turn reports (StateReport,
    any order): settlements, public order and tax, treasury, armies, sieges, events. "" without reports."""
    states = sorted(states, key=lambda x: x[0])
    if not states:
        return ""
    (t0, first), (t1, last) = states[0], states[-1]
    lines = [f"OUTCOMES (from the game's own reports, T{t0} to T{t1}; these are facts)"]
    held0, held1 = {s.id: s for s in first.settlements}, {s.id: s for s in last.settlements}
    lost, gained = [x for x in held0 if x not in held1], [x for x in held1 if x not in held0]
    lines.append(f"Settlements: {len(held0)} at T{t0}, {len(held1)} at T{t1}."
                 + "".join(f" LOST {held0[x].name} (now held by {_who(_holder(states, x))})" for x in lost)
                 + "".join(f" GAINED {held1[x].name}" for x in gained))
    for sid in dict.fromkeys(list(held0) + list(held1)):
        line = _order_line(sid, states, sid in held1)
        if line:
            lines.append(line)
    sieges: dict[str, tuple[int, str | None]] = {}
    for t, rep in states:
        for s in rep.settlements:
            if s.siege:
                sieges.setdefault(s.name, (t, s.siege.faction))
    if sieges:
        lines.append("Besieged: " + ", ".join(f"{n} by {_who(f)} from T{t}" for n, (t, f) in sieges.items()))
    lo = min(states, key=lambda x: x[1].treasury)
    low = f" (low {lo[1].treasury} T{lo[0]})" if lo[1].treasury < min(first.treasury, last.treasury) else ""
    lines.append(f"Treasury {first.treasury} -> {last.treasury}{low}; income/turn {first.income} -> {last.income}.")
    lines.append(f"Armies: {len(first.armies)} with {sum(a.men for a in first.armies)} men at T{t0}, "
                 f"{len(last.armies)} with {sum(a.men for a in last.armies)} men at T{t1}.")
    ev = _events(states, {s.name for _, rep in states for s in rep.settlements}, last.faction)
    if ev:
        lines += ["Events:"] + [f"- {e}" for e in ev]
    text = "\n".join(lines)
    return text if len(text.encode()) <= OUTCOMES_MAX else text.encode()[:OUTCOMES_MAX].decode(errors="ignore")


def review_prompt(name: str, faction: str, turns: list[tuple[int, str, list[str]]], outcomes: str = "") -> str:
    """turns: (turn, the ruler's note, its order results) for the stretch under review; outcomes: the
    outcomes_section for the same stretch."""
    blocks = []
    for t, note, results in turns:
        lines = "\n".join(f"- {r}" for r in results) or "- (none)"
        blocks.append(f"TURN {t}\nNote: {note}\nResults:\n{lines}")
    return (f"You are reviewing the play of {name}, ruler of {faction}, over the turns given below.\n\n"
            + "\n\n".join(blocks) + "\n\n"
            + (outcomes + "\n\n" if outcomes else "")
            + "Write at most 3 lessons about playing Medieval II better (strategy, economy, war, diplomacy). "
            "Each lesson is a plain instruction to your future self and must link a decision to an outcome: "
            '"I did X on turn N; Y happened by turn M", so it says what to do or avoid next time. '
            + ("The OUTCOMES above are what really happened: a lesson must never contradict them, and a "
               "decision that came before a loss (a settlement, an army, the treasury, public order) was "
               "not a success. " if outcomes else "")
            + "Cite specific turns in the evidence.\n\n"
            "Do NOT write lessons about the software around the game (rejected or malformed orders, "
            '"seat error", empty turns, things "not in sight" or "unknown", unit-merge limits): those are '
            "bugs being fixed, not lessons. Prefer no lesson to a weak one: when the outcomes show no "
            "clear cause and effect, answer with an empty list.\n\n"
            'Respond with JSON only: {"lessons": [{"text": "...", "evidence": "..."}]}')


def parse_review(text: str) -> list[dict[str, str]]:
    """The lessons in a review answer (fenced or with prose around it); [] if malformed."""
    if not isinstance(text, str):
        return []
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return []
    items = data.get("lessons") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not (isinstance(item, dict) and isinstance(item.get("text"), str)
                and isinstance(item.get("evidence", ""), str)):
            return []
        out.append({"text": item["text"], "evidence": item.get("evidence", "")})
    return out


def code_version(repo: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=5, check=True).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def main(argv: list[str]) -> int:
    root = Path(argv[0]).expanduser()
    if root.suffix == ".toml":  # a game config: the lessons kept beside its turn folders
        from parley.config import load_config
        root = load_config(root).turn_root / "lessons"
    if argv[1:2] == ["veto"] and len(argv) == 3:
        lesson = veto(root, argv[2])
        print(f"vetoed {lesson.id}: {lesson.text}" if lesson else f"no lesson {argv[2]}")
        return 0 if lesson else 1
    for path in sorted(root.glob("*.json")):
        print(f"== {path.stem}")
        for x in load(root, path.stem):
            print(f"[{x.id}] {'VETOED ' if x.vetoed else ''}{x.text}\n"
                  f"    ({x.game_id} turn {x.turn}, code {x.version or '?'}) {x.evidence}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
