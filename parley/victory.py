"""The campaign's victory conditions and turn limit, read from the game's own files.

The author, 2026-10-29: "does it understand win conditions?" and "does it understand [it] only has so
many turns to do so". Neither was in the prompt. The game keeps both on disk: each faction's goal
in descr_win_conditions.txt, and the length in descr_strat.txt (start and end year, years a turn).
"""

import json
import re
from pathlib import Path
from typing import Callable, NamedTuple

CAMPAIGN = Path("data") / "world" / "maps" / "campaign" / "imperial_campaign"


def campaign_dir(game_dir: Path, mod: str = "parley") -> Path:
    """The mod's own campaign files when it has them, else the game's."""
    own = Path(game_dir) / "mods" / mod / CAMPAIGN
    return own if (own / "descr_win_conditions.txt").exists() else Path(game_dir) / CAMPAIGN


def win_conditions(text: str) -> dict[str, dict]:
    """faction -> {"long": {"hold": [...], "take": N}, "short": {"hold": [...], "take": N, "outlive": [...]}}.

    A block is a faction's name, then its lines, until a blank line. Lines after `short_campaign`
    belong to the short campaign; `;` starts a comment (the short campaign's hold list is usually
    commented out)."""
    out: dict[str, dict] = {}
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [ln.split(";", 1)[0].strip() for ln in block.splitlines()]
        lines = [ln for ln in lines if ln]
        if not lines:
            continue
        faction, cur = lines[0], "long"
        goal = {"long": {"hold": [], "take": None}, "short": {"hold": [], "take": None, "outlive": []}}
        for ln in lines[1:]:
            words = ln.split()
            if words[0] == "short_campaign":
                cur, words = "short", words[1:]
                if not words:
                    continue
            if words[0] == "hold_regions":
                goal[cur]["hold"] = words[1:]
            elif words[0] == "take_regions" and len(words) > 1 and words[1].isdigit():
                goal[cur]["take"] = int(words[1])
            elif words[0] == "outlive":
                goal["short"]["outlive"] = words[1:]
        out[faction] = goal
    return out


def turn_limit(strat_text: str) -> int | None:
    """Turns the campaign lasts: (end year - start year) / years a turn (live: 1080-1530 at 2.00 = 225)."""
    start = re.search(r"(?m)^start_date\s+(\d+)", strat_text)
    end = re.search(r"(?m)^end_date\s+(\d+)", strat_text)
    scale = re.search(r"(?m)^timescale\s+([\d.]+)", strat_text)
    if not (start and end and scale) or float(scale.group(1)) <= 0:
        return None
    return round((int(end.group(1)) - int(start.group(1))) / float(scale.group(1)))


def _region(name: str) -> str:
    return name.removesuffix("_Province").replace("_", " ")


def _outlive_standing(names: list[str], factions) -> str:
    """"France holds 7 settlements, Scotland holds 2." for the factions the goal says to outlive,
    from the report's factions list (FactionView: id, name, settlements); "" when it has none of them."""
    by_name = {}
    for f in factions or []:
        for key in (getattr(f, "id", ""), getattr(f, "name", "")):
            by_name.setdefault(str(key).lower(), f)
    out = []
    for n in names:
        f = by_name.get(n.lower())
        if f is None or f.settlements is None:
            continue
        label = n.replace("_", " ").title()
        if f.settlements == 0:
            out.append(f"{label} is destroyed (0 settlements)")
        else:
            out.append(f"{label} holds {f.settlements} settlement{'s' if f.settlements != 1 else ''}")
    return ", ".join(out) + "." if out else ""


def victory_line(faction: str, turn: int, held: int, folder: Path, length: str = "long",
                 history: "list[Snapshot] | None" = None, factions=None) -> str | None:
    """The goal, how far along, and the turns left; None without the files. With `history` (see
    read_history) it adds the economy, a phase line and a note on a plan that has not moved. With
    `factions` (the report's factions list) it shows how many settlements each faction to outlive holds."""
    try:
        goals = win_conditions((folder / "descr_win_conditions.txt").read_text(errors="replace"))
        limit = turn_limit((folder / "descr_strat.txt").read_text(errors="replace"))
    except OSError:
        return None
    goal = goals.get(faction, {}).get(length)
    if not goal or not goal.get("take"):
        return None
    parts = []
    if goal["hold"]:
        parts.append("hold " + " and ".join(_region(r) for r in goal["hold"]))
    parts.append(f"rule {goal['take']} regions in all (you hold {held})")
    if goal.get("outlive"):
        parts.append("outlive " + " and ".join(goal["outlive"]))
    text = "To win the campaign: " + ", ".join(parts) + "."
    if standing := _outlive_standing(goal.get("outlive") or [], factions):
        text += " " + standing
    if limit:
        # the report's turn 0 is the game's turn 1, when the game shows the whole limit remaining
        left = max(limit - turn, 0)
        text += f" The campaign ends after turn {limit}: {left} turns left. If it ends first, you have lost."
    left = max(limit - turn, 0) if limit else None
    return "\n".join([text, *economy_lines(history or [], left)])


# --- the economy, as facts (the author: money is the engine; no rigid pace line, the ruler decides) ---
HISTORY = 20       # earlier turns read from the turn folders
COMPARE_AGE = 10   # "income ten turns ago": the snapshot nearest this age, else the oldest one
MIN_AGE = 3        # no comparison with a snapshot younger than this
STALL_AGE = 15     # turns without growth before the realm counts as stalled
STALL_GROWTH = 0.05  # income up by less than this over STALL_AGE, with no new settlement, is stalled
BUILDING_TURNS = 60  # before this turn, being behind on regions is normal
GROWING = 0.10     # income up by this over COMPARE_AGE also counts as building
LATE_TURNS = 40    # turns left at or below which the late-game line shows
SAME_GOAL = 4      # a plan whose first goal has stood this many turns is reported


class Snapshot(NamedTuple):
    turn: int
    income: int
    treasury: int
    settlements: int
    armies: int = 0
    upkeep: int | None = None  # army upkeep a turn, positive; None when the report has no such item
    costs: int | None = None   # all regular costs a turn, positive
    plan: str = ""             # the standing plan the ruler wrote that turn (earlier turns only)
    towns: dict | None = None  # current snapshot only: settlement name (lowercase) -> owning faction
    faction: str = ""          # current snapshot only: the ruler's own faction


def snapshot_of(report) -> Snapshot:
    """The current turn's snapshot from a StateReport (its plan is not written yet)."""
    parts = report.income_parts or {}
    up = parts.get("army upkeep")
    towns = {s.name.lower(): report.faction for s in report.settlements}
    for s in [*getattr(report, "remembered", []), *getattr(report, "nearby_settlements", [])]:  # nearby is newest
        towns.setdefault(s.name.lower(), s.faction)
        if s.faction != report.faction and towns[s.name.lower()] == report.faction:
            towns[s.name.lower()] = s.faction  # lost since: the foreign owner wins
    return Snapshot(report.turn, report.income, report.treasury, len(report.settlements), len(report.armies),
                    -up if up is not None else None, -sum(v for v in parts.values() if v < 0) or None, towns=towns, faction=report.faction)


def read_history(path_for: Callable[[str, int, str], Path], report) -> list[Snapshot]:
    """Current snapshot first, then earlier turns newest first, read from the turn folders
    (state.json for the numbers, orders.json for the plan); turns with no folder are skipped."""
    out = [snapshot_of(report)]
    for turn in range(report.turn - 1, max(report.turn - 1 - HISTORY, -1), -1):
        folder = path_for(report.game_id, turn, report.faction)
        try:
            d = json.loads((folder / "state.json").read_text())
            parts = d.get("income_parts") or {}
            parts = parts if isinstance(parts, dict) else {}
            up = parts.get("army upkeep")
            snap = Snapshot(turn, int(d["income"]), int(d["treasury"]), len(d["settlements"]), len(d.get("armies") or []),
                            -up if up is not None else None, -sum(v for v in parts.values() if v < 0) or None)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        try:
            snap = snap._replace(plan=str(json.loads((folder / "orders.json").read_text()).get("plan") or ""))
        except (OSError, ValueError, AttributeError):
            pass
        out.append(snap)
    return out


def first_goal(plan: str) -> str:
    """The plan's first goal, lowercased, without numbering or turn numbers, to its first colon or full stop."""
    text = re.split(r"\n|\s\d+[.)]\s", plan.strip(), maxsplit=1)[0]
    text = re.sub(r"^\s*\d+[.)]\s*", "", text)
    text = re.sub(r"\(?\b(?:by |in )?turns? \d+\b\)?", "", text, flags=re.I)
    text = re.split(r"[:;]|\.(?:\s|$)", text, maxsplit=1)[0]
    return re.sub(r"\s+", " ", text).strip(" ,-").lower()


def _then(history: list[Snapshot]) -> Snapshot | None:
    """The snapshot to compare with: about COMPARE_AGE turns back, else the oldest at least MIN_AGE old."""
    now = history[0]
    old = [h for h in history[1:] if now.turn - h.turn >= MIN_AGE]
    if not old:
        return None
    at_age = [h for h in old if now.turn - h.turn >= COMPARE_AGE]
    return max(at_age, key=lambda h: h.turn) if at_age else min(old, key=lambda h: h.turn)


def _phase(history: list[Snapshot], left: int | None) -> str | None:
    now = history[0]
    if left is not None and left <= LATE_TURNS:
        text = f"{left} turns left: a rich realm takes several settlements a turn."
        if now.upkeep and now.armies:
            each = now.upkeep / now.armies
            text += (f" Your {now.armies} armies cost about {each:.0f} each a turn; income before army upkeep"
                     f" is {now.income + now.upkeep}, enough to keep roughly {(now.income + now.upkeep) / each:.0f} of them.")
        return text
    old = [h for h in history[1:] if now.turn - h.turn >= STALL_AGE]
    if old:
        h = max(old, key=lambda h: h.turn)
        grew = now.income > h.income + abs(h.income) * STALL_GROWTH
        if not grew and now.settlements <= h.settlements:
            return (f"Neither income nor land has grown in {now.turn - h.turn} turns "
                    f"({h.settlements} settlements then, {now.settlements} now): something has to change.")
    then = _then(history)
    growing = then is not None and now.income > then.income + abs(then.income) * GROWING
    if now.turn <= BUILDING_TURNS or growing:
        return ("Building phase: being behind on regions is normal while income grows; "
                "the winners turn money into armies later.")
    return None


def _named(goal: str, towns: dict) -> set[str]:
    """Settlement names the report knows that appear in a (lowercase) goal."""
    return {n for n in towns if re.search(rf"\b{re.escape(n)}\b", goal)}


def _stuck_plan(history: list[Snapshot]) -> str | None:
    """A foreign settlement the first goal has named for SAME_GOAL+ plans running and the faction still
    lacks; with no settlement name in the newest goal, the same exact first goal for that long."""
    towns = history[0].towns or {}
    plans = [(h.turn, first_goal(h.plan)) for h in history[1:] if first_goal(h.plan)]  # newest first
    if not plans:
        return None
    named = _named(plans[0][1], towns)
    if named:
        best = None
        for name in sorted(named):
            if towns[name] == history[0].faction:
                continue  # already yours
            run = []
            for turn, g in plans:
                if name not in _named(g, towns):
                    break
                run.append(turn)
            if len(run) >= SAME_GOAL and (best is None or len(run) > len(best[1])):
                best = (name, run)
        if best:
            name, run = best
            return (f"Your plan has aimed at {name.title()} since turn {run[-1]} ({run[0] - run[-1] + 1} turns); "
                    f"it is still {towns[name].replace('_', ' ').title()}'s.")
        return None
    run = []
    for turn, g in plans:
        if g != plans[0][1]:
            break
        run.append(turn)
    if len(run) >= SAME_GOAL:
        return f"Your plan has said '{plans[0][1]}' since turn {run[-1]} ({run[0] - run[-1] + 1} turns)."
    return None


def economy_lines(history: list[Snapshot], left: int | None) -> list[str]:
    """Facts about the economy and the plan, from `history` (current snapshot first); [] without any."""
    if not history:
        return []
    now = history[0]
    text = f"Economy: income {now.income} a turn"
    then = _then(history)
    if then:
        age = now.turn - then.turn
        change = f"; {(now.income - then.income) / abs(then.income):+.0%}" if then.income else ""
        text += f" (was {then.income} {age} turns ago{change}); treasury {now.treasury} (was {then.treasury})."
    else:
        text += f"; treasury {now.treasury}."
    if now.upkeep and now.costs:
        text += f" Army upkeep is {now.upkeep / now.costs:.0%} of your regular costs ({now.upkeep} of {now.costs} a turn)."
    lines = [text]
    ago = {a: min(history[1:], key=lambda h: abs(now.turn - h.turn - a), default=None) for a in (10, 20)}
    if ago[10] and now.turn - ago[10].turn >= MIN_AGE:
        parts = [f"{ago[a].settlements} {now.turn - ago[a].turn} turns ago" for a in (10, 20)
                 if ago[a] and now.turn - ago[a].turn >= (MIN_AGE if a == 10 else STALL_AGE)
                 and (a == 10 or ago[a] is not ago[10])]
        lines[0] += f" Settlements: {now.settlements} now ({', '.join(parts)})."
    lines += [x for x in (_phase(history, left), _stuck_plan(history)) if x]
    return lines
