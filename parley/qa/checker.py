"""Check QA bench case expectations against bridge logs, state.json, and order results."""

from __future__ import annotations

import datetime as _dt
import re
from typing import Literal

from pydantic import BaseModel

from parley.qa.cases import Case, Expect

_SEGMENT_RE = re.compile(r"^([^\[\]]+)\[([^\[\]]+)\]$")


class Verdict(BaseModel):
    outcome: Literal["pass", "fail", "inconclusive", "pending"]
    evidence: str


def _substitute(value: str | int | None, targets: dict[str, str | int]) -> str | int | None:
    if value is None or not targets or not isinstance(value, str):
        return value
    if value.startswith("$") and value[1:] in targets:
        return targets[value[1:]]
    out = value
    for key in sorted(targets, key=len, reverse=True):
        out = out.replace(f"${key}", str(targets[key]))
    return out


def _resolve_state_path(state: dict, path: str) -> tuple[bool, object]:
    cur: object = state
    for segment in path.split("."):
        m = _SEGMENT_RE.match(segment)
        if m:
            field_name, selector = m.group(1), m.group(2)
            if not isinstance(cur, dict) or field_name not in cur:
                return False, None
            seq = cur[field_name]
            if not isinstance(seq, list):
                return False, None
            if "=" in selector:
                sel_key, _, sel_val = selector.partition("=")
                matched_item = None
                for item in seq:
                    if not isinstance(item, dict):
                        continue
                    if sel_key in item and str(item[sel_key]) == sel_val:
                        matched_item = item
                        break
                    if sel_key == "name" and "name" not in item and str(item.get("id")) == sel_val:
                        matched_item = item
                        break
                    if sel_key == "id" and "id" not in item and str(item.get("name")) == sel_val:
                        matched_item = item
                        break
                if matched_item is None:
                    return False, None
                cur = matched_item
            elif selector.isdigit():
                idx = int(selector)
                if 0 <= idx < len(seq):
                    cur = seq[idx]
                else:
                    return False, None
            else:
                return False, None
        else:
            if not isinstance(cur, dict) or segment not in cur:
                return False, None
            cur = cur[segment]
    return True, cur


def _state_matches(actual: object, expected: str | int | None) -> tuple[bool, str]:
    if expected is None:
        if actual is None or actual == [] or actual == {} or actual == "":
            return False, f"empty ({actual!r})"
        return True, repr(actual)
    if isinstance(actual, list):
        for item in actual:
            if item == expected or str(item) == str(expected) or re.search(str(expected), str(item)):
                return True, str(item)
        return False, f"{actual!r} != {expected!r}"
    if actual == expected or str(actual) == str(expected):
        return True, str(actual)
    return False, f"{actual!r} != {expected!r}"


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _at_least(actual: object, floor: object) -> tuple[bool, str]:
    """A number at or above the floor; anything that isn't a number (or an unfilled `$name`) fails."""
    have, need = _number(actual), _number(floor)
    if need is None:
        return False, f"{actual!r}, but the floor {floor!r} is not a number"
    if have is None:
        return False, f"{actual!r} is not a number (need >= {floor})"
    if have < need:
        return False, f"{actual!r} < {floor}"
    return True, f"{actual!r} >= {floor}"


_LOG_TIME_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", re.MULTILINE)
# lines the bridge's M.setup writes on a (re)load: what follows comes from a game started again (live
# 05:30:31, after the 05:29 bench crash: "papal window: notice (kept across the reload)" came first)
_RESTART_RE = re.compile(
    r"^.*(?:bridge (?:re)?loaded|kept across the reload|PREVIOUS RUN ENDED MID-STEP).*$", re.MULTILINE
)


def _line_time(text: str, pos: int) -> _dt.datetime | None:
    start = text.rfind("\n", 0, pos) + 1
    m = _LOG_TIME_RE.match(text, start)
    return _dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None


def alive_after(log_text: str, after: str, seconds: float) -> tuple[bool, str]:
    """The game was still running `seconds` after the first line matching `after`: a later line of
    the bridge log (only the game writes it) timed at least that long after, before any bridge
    (re)load line. (True, the line that proves it) or (False, why not)."""
    m = re.search(after, log_text, re.MULTILINE)
    if not m:
        return False, f"log {after!r} not found"
    t0 = _line_time(log_text, m.start())
    if t0 is None:
        return False, f"no time on the line matching {after!r}"
    line_end = log_text.find("\n", m.end())
    rest_from = len(log_text) if line_end < 0 else line_end + 1
    restart = _RESTART_RE.search(log_text, rest_from)
    upto = restart.start() if restart else len(log_text)
    last = None
    for tm in _LOG_TIME_RE.finditer(log_text, rest_from, upto):
        t = _dt.datetime.strptime(tm.group(1), "%Y-%m-%d %H:%M:%S")
        last = t
        if (t - t0).total_seconds() >= seconds:
            end = log_text.find("\n", tm.start())
            line = log_text[tm.start(): end if end >= 0 else len(log_text)]
            return True, f"alive {seconds:g} s after {t0:%H:%M:%S}: {line.strip()}"
    gap = f"{(last - t0).total_seconds():g} s" if last else "no line"
    if restart:
        return False, (f"not alive {seconds:g} s after {t0:%H:%M:%S}: the bridge loaded again "
                       f"({restart.group(0).strip()}) with the last line of the old game at +{gap}")
    return False, f"not yet {seconds:g} s of log after {t0:%H:%M:%S} (last line at +{gap})"


def _short(text: str) -> str:
    """A log match for evidence: one line as is, a match over many lines as its first and last."""
    lines = text.strip().splitlines()
    return text if len(lines) <= 1 else f"{lines[0]} ... {lines[-1]}"


def _check_expect(
    exp: Expect,
    targets: dict[str, str | int],
    log_text: str,
    state: dict | None,
    results: list[dict] | None,
) -> tuple[bool, str]:
    if exp.alive is not None:
        return alive_after(log_text, str(_substitute(exp.after, targets)), exp.alive)
    if exp.log is None and exp.state is None and exp.order_ok is None and not exp.any_of:
        return False, "empty expect"

    reasons: list[str] = []

    if exp.any_of:
        misses: list[str] = []
        for alt in exp.any_of:
            ok, detail = _check_expect(alt, targets, log_text, state, results)
            if ok:
                reasons.append(detail)
                break
            misses.append(detail)
        else:
            return False, "none of: " + " | ".join(misses)

    if exp.order_ok is not None:
        # results the caller matched to the case's own orders are final, even when empty: the report's
        # last_results is the turn before it, which may be another case's (live 10-30 18:00)
        if results is not None:
            effective = results
        else:
            effective = state.get("last_results", []) if isinstance(state, dict) else []
        if exp.order_ok:
            ok = bool(effective) and all(bool(r.get("ok")) for r in effective)
        else:
            ok = bool(effective) and any(not bool(r.get("ok")) for r in effective)
        if not ok:
            return False, f"order_ok={exp.order_ok} not met ({effective!r})"
        reasons.append(f"order_ok={exp.order_ok}")

    if exp.log is not None:
        pattern = str(_substitute(exp.log, targets))
        m = re.search(pattern, log_text, re.MULTILINE)
        if not m:
            return False, f"log {pattern!r} not found"
        reasons.append(f"log: {_short(m.group(0))}")

    if exp.state is not None:
        if state is None:
            return False, f"state {exp.state!r}: state is None"
        state_path = str(_substitute(exp.state, targets))
        target_eq = _substitute(exp.equals, targets)
        found, actual = _resolve_state_path(state, state_path)
        if not found:
            return False, f"state {state_path!r} not found"
        if exp.at_least is not None:
            matched, detail = _at_least(actual, _substitute(exp.at_least, targets))  # type: ignore[arg-type]
            if not matched:
                return False, f"state {state_path}={detail}"
            reasons.append(f"state {state_path}={detail}")
            return True, ", ".join(reasons)
        matched, detail = _state_matches(actual, target_eq)
        if not matched:
            return False, f"state {state_path}={detail}"
        reasons.append(f"state {state_path}={detail}")

    return True, ", ".join(reasons)


def check(
    case: Case,
    log_text: str,
    state: dict | None,
    results: list[dict] | None,
    turns_used: int,
) -> Verdict:
    has_independent_evidence = any(e.independent for e in case.expect)
    if not has_independent_evidence:
        return Verdict(
            outcome="fail",
            evidence="order_ok alone cannot pass a case; at least one log or state expect is required",
        )

    passed_evidences: list[str] = []
    missing_reasons: list[str] = []

    for exp in case.expect:
        ok, detail = _check_expect(exp, case.targets, log_text, state, results)
        if ok:
            passed_evidences.append(detail)
        else:
            missing_reasons.append(detail)

    if not missing_reasons:
        return Verdict(outcome="pass", evidence="; ".join(passed_evidences))

    evidence = "; ".join(missing_reasons)
    if turns_used < case.max_turns:
        return Verdict(outcome="pending", evidence=evidence)
    if case.chance:
        return Verdict(outcome="inconclusive", evidence=evidence)
    return Verdict(outcome="fail", evidence=evidence)
