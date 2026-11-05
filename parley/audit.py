"""Turn audit: plain checks over a game's turn folders that find problems before anyone asks.

Each finding lands in one bin:
- bridge: the bridge (or the seat around it) got something wrong; it needs a code fix.
- ruler: the ruler made a mistake the game or the checker caught; it should be told plainly.
- option: the ruler had an order that fit and never used it.

A turn folder holds the report the ruler read (state.json), its orders (orders.json) and what
became of them (results.json from the game, rejected.json from the checker). No LLM: every
finding is a fact read from those files. The author, 2026-10-29: "why do I have to ask you in order to
get this information".
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from parley.validate import plain_name

BINS = {"bridge": "Bridge bugs (need a code fix)",
        "ruler": "Ruler mistakes (the ruler should be told)",
        "option": "Unused options (an order fit and wasn't used)"}
MOVES = {"move_army": "army", "march_on": "army", "withdraw": "army", "move_agent": "agent"}
RUNWAY = 5  # turns of money left at the current loss that count as running out


@dataclass(frozen=True)
class Finding:
    bin: str
    check: str
    faction: str
    turn: int
    detail: str

    @property
    def key(self) -> str:
        """The same problem on another turn has the same key (numbers and coordinates dropped)."""
        return f"{self.bin}|{self.check}|{self.faction}|{_shape(self.detail)}"


def _shape(text: str) -> str:
    return re.sub(r"\d+", "N", text)


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _positions(state: dict) -> dict:
    """Where each own army (by id and by leader) and agent stood in a report."""
    pos = {}
    for a in state.get("armies", []):
        for name in (a.get("id"), a.get("leader")):
            if name and a.get("x") is not None:
                pos[name] = (a["x"], a["y"])
    for a in state.get("agents", []):
        if a.get("id") and a.get("x") is not None:
            pos[a["id"]] = (a["x"], a["y"])
    return pos


def _own_names(state: dict) -> set:
    names = set()
    for a in state.get("armies", []):
        names.update(n for n in (a.get("id"), a.get("leader")) if n)
    names.update(a["id"] for a in state.get("agents", []) if a.get("id"))
    return names


def _mover(order: dict) -> str | None:
    return order.get("army") or order.get("agent") or order.get("who")


def _target(order: dict, state: dict):
    """The tile an order moves to, or a settlement's tile, or None when unknown."""
    if "x" in order and "y" in order:
        return (order["x"], order["y"])
    name = order.get("target_settlement") or order.get("to_settlement")
    for s in state.get("settlements", []) + state.get("nearby_settlements", []):
        if name and name in (s.get("id"), s.get("name")) and s.get("x") is not None:
            return (s["x"], s["y"])
    return None


def _results(folder: Path, orders: list) -> list[tuple[dict, dict]]:
    """(order, outcome) for every game result; the result's index points into orders."""
    out = []
    for res in _load(folder / "results.json") or []:
        i = res.get("index")
        if isinstance(i, int) and 0 <= i < len(orders):
            out.append((orders[i], res))
    return out


def refusals(folder: Path, orders: list | None = None) -> list[tuple[dict, dict]]:
    """(order, outcome) for everything refused in a turn folder: by the game, then by the checker
    (whose orders aren't kept, so only the type is known)."""
    if orders is None:
        orders = (_load(folder / "orders.json") or {}).get("orders", [])
    out = [(o, r) for o, r in _results(folder, orders) if not r.get("ok")]
    return out + [({"type": r.get("type")}, r) for r in _load(folder / "rejected.json") or []]


def refusal_key(kind, reason: str) -> str:
    """The same refusal on another turn has the same key (numbers and coordinates dropped)."""
    return f"{kind}: {_shape(reason or '')}"


# the name runs to the last quote: live (run9 turn 45) "unknown army 'Captain Arthur's Army'"
# read as 'Captain Arthur', a real army, and woke the watch as a bridge bug
UNKNOWN = re.compile(r"unknown (?:army|agent) '(.+)'(?=[^']*$)")
_plain = plain_name  # the checker reads near-miss names itself now; a finding here is one it missed


def _leaders(state: dict) -> dict:
    """garrison id -> the leader who marches out with it (the id stays with the town)."""
    return {a["id"]: a["leader"] for a in state.get("armies", [])
            if a.get("id", "").startswith("garrison:") and a.get("leader")}


def audit_turn(folder: Path, turn: int, faction: str, next_state: dict | None,
               later_state: dict | None = None) -> list[Finding]:
    """Findings for one ruler's turn folder; next_state is the following turn's report, later_state
    the one after. A move ordered here runs at the next turn's start and can land after that
    turn's report is written (live: a diplomat on his old tile in it, on his target a minute
    later), so whether a mover moved is read from later_state."""
    found = []
    state = _load(folder / "state.json")
    orders_doc = _load(folder / "orders.json")
    if state is None:
        return found
    if orders_doc is None:
        if next_state is not None:  # a later turn exists, so this one went unanswered
            found.append(Finding("bridge", "unanswered", faction, turn, "no orders came back for this turn"))
        return found
    note = orders_doc.get("note") or ""
    if note.startswith("seat error"):
        found.append(Finding("bridge", "seat error", faction, turn, note[:160]))
    orders = orders_doc.get("orders", [])
    own = _own_names(state)
    refused = refusals(folder, orders)

    # a name the ruler's own report listed, refused as unknown
    for o, r in refused:
        m = UNKNOWN.search(r.get("reason") or "")
        if not m:
            continue
        name = m.group(1)
        agents = {a["id"] for a in state.get("agents", []) if a.get("id")}
        if "unknown agent" in (r.get("reason") or "") and name in own and name not in agents:
            # live (2026-10-29, turn 138): France moved its generals by move_agent
            found.append(Finding("ruler", "agent order for a general", faction, turn,
                                 f"{o.get('type')}: '{name}' leads an army; armies move by move_army"))
            continue
        if name in own:
            idx = r.get("index")
            earlier = orders[:idx] if isinstance(idx, int) else []
            # only a move that ran: live (run9 turn 32) France's move_army for Captain Luquin was
            # refused unknown too (he died besieging Caen before France's orders ran)
            refused_at = {q.get("index") for _, q in refused}
            moved_before = any(_mover(p) == name and p.get("type") in MOVES and i not in refused_at
                               for i, p in enumerate(earlier))
            # live (2026-10-29): England merged garrison:Edinburgh into Rufus, then ordered five
            # disbands from it; the merge had taken the garrison away, as it should
            merged_away = any(p.get("type") == "merge_armies" and p.get("army") == name for p in earlier)
            if merged_away:
                found.append(Finding("ruler", "used after merging it away", faction, turn,
                                     f"{o.get('type')}: '{name}' was merged into another army by an earlier "
                                     f"order this turn, so it no longer exists"))
            elif moved_before:
                why = " (a garrison's id stays with its town)" if name.startswith("garrison:") else ""
                found.append(Finding("bridge", "listed name refused", faction, turn,
                                     f"{o.get('type')}: '{name}' came back unknown after an earlier order this "
                                     f"turn moved it{why}"))
            elif next_state is not None and name in _own_names(next_state):
                found.append(Finding("bridge", "listed name refused", faction, turn,
                                     f"{o.get('type')}: '{name}' came back unknown, yet it is in the reports "
                                     f"before and after"))
            # else: gone before its order ran (a battle, a merge); the refusal told the ruler
            continue
        near = sorted(n for n in own if _plain(n) == _plain(name))
        if near:
            found.append(Finding("bridge", "near-miss name", faction, turn,
                                 f"{o.get('type')}: '{name}' refused; its own '{near[0]}' was meant"))
        else:
            found.append(Finding("ruler", "name not in report", faction, turn,
                                 f"{o.get('type')}: named '{name}', which isn't one of its own"))

    # an order reported done whose mover stood still
    if later_state is not None:
        before, after, leaders = _positions(state), _positions(later_state), _leaders(state)
        for o, r in _results(folder, orders):
            kind = o.get("type")
            name = _mover(o)
            if not r.get("ok") or kind not in MOVES or name not in before:
                continue
            target = _target(o, state)
            if target is None or before[name] == target:
                continue
            # march_on from the next tile to a town it doesn't hold besieges it there (live, run8)
            own_towns = {s.get("id") for s in state.get("settlements", [])}
            if kind == "march_on" and o.get("target_settlement") not in own_towns \
                    and max(abs(before[name][0] - target[0]), abs(before[name][1] - target[1])) <= 1:
                continue
            follow = leaders.get(name, name)  # a garrison that marched out goes by its leader
            if follow in after and after[follow] == before[name]:
                found.append(Finding("bridge", "done but didn't move", faction, turn,
                                     f"{kind} {name} to {target}: reported done, still at {before[name]} two reports later"))

    # money running out at the current loss, and nothing disbanded
    income, treasury = state.get("income"), state.get("treasury")
    if isinstance(income, int) and isinstance(treasury, int) and income < 0:
        left = max(treasury, 0) // -income
        if left < RUNWAY:
            found.append(Finding("ruler", "money running out", faction, turn,
                                 f"treasury {treasury}, income {income} a turn: {left} turns left"))
        if not any(o.get("type") == "disband" for o in orders):
            found.append(Finding("option", "in debt, no disband", faction, turn,
                                 f"income {income} a turn and no disband order"))
    return found


def audit_game(game_dir: Path, since: int | None = None) -> list[Finding]:
    """Every finding in a game, turn by turn, plus the checks that span turns; with since, only
    turns from there on (one earlier is read for the repeats)."""
    turns = sorted(p for p in Path(game_dir).glob("turn-*") if p.is_dir())
    if since is not None:
        turns = [t for t in turns if int(t.name.removeprefix("turn-")) >= since - 1]
    found = []
    by_faction = defaultdict(list)  # faction -> [(turn, folder)]
    for t in turns:
        n = int(t.name.removeprefix("turn-"))
        for d in sorted(p for p in t.iterdir() if p.is_dir()):
            by_faction[d.name].append((n, d))
    for faction, seq in by_faction.items():
        prev_reasons = set()
        for i, (n, d) in enumerate(seq):
            nxt = _load(seq[i + 1][1] / "state.json") if i + 1 < len(seq) else None
            later = _load(seq[i + 2][1] / "state.json") if i + 2 < len(seq) else None
            found += audit_turn(d, n, faction, nxt, later)
            # the same refusal again: the ruler didn't take in why the last one failed
            orders = (_load(d / "orders.json") or {}).get("orders", [])
            reasons = {refusal_key(r.get("type"), r.get("reason")) for _, r in refusals(d, orders)}
            for again in sorted(reasons & prev_reasons):
                found.append(Finding("ruler", "same refusal again", faction, n, again))
            prev_reasons = reasons
            # a move refused for want of a land path, and no fleet boarded then or the turn after
            nxt_orders = _load(seq[i + 1][1] / "orders.json") if i + 1 < len(seq) else None
            if nxt_orders is not None and any("can't be reached over land" in (r.get("reason") or "")
                                              for _, r in _results(d, orders)):
                if not any(o.get("type") == "board" for o in orders + nxt_orders.get("orders", [])):
                    found.append(Finding("option", "across the sea, no board", faction, n,
                                         "a move needed a fleet and no board order followed"))
    return [f for f in found if since is None or f.turn >= since]


SEEN = "audit-seen.json"  # in the game's turn folder: problem keys already alerted
ALERTS_PER_TURN = 8


def new_findings(game_dir: Path, findings: list[Finding]) -> list[Finding]:
    """The first finding of each key not alerted before; remembers them."""
    path = Path(game_dir) / SEEN
    seen = set(_load(path) or [])
    new, keys = [], set()
    for f in findings:
        if f.key not in seen and f.key not in keys:
            keys.add(f.key)
            new.append(f)
    if keys:
        path.write_text(json.dumps(sorted(seen | keys)))
    return new


def alert_lines(new: list[Finding], game_id: str) -> list[str]:
    """One line per new problem for the humans' audit channel, the bridge bugs first."""
    order = {b: i for i, b in enumerate(BINS)}
    new = sorted(new, key=lambda f: (order[f.bin], f.turn))
    lines = [f"Audit, turn {f.turn} [{f.bin}] {f.check} ({f.faction}): {f.detail}"[:400]
             for f in new[:ALERTS_PER_TURN]]
    if len(new) > ALERTS_PER_TURN:
        lines.append(f"... and {len(new) - ALERTS_PER_TURN} more new problems: just audit {game_id}")
    return lines


RULER_WORDS = {
    "same refusal again": "The same order was refused the same way two turns running ({detail}).",
    "money running out": "Your money is running out: {detail}.",
    "used after merging it away": "An order used an army that an earlier order had merged away ({detail}). "
                                  "Order for an army before merging it, not after.",
    "name not in report": "An order named someone who isn't yours ({detail}). Name armies and agents "
                          "exactly as your report lists them.",
    "in debt, no disband": "You lose money every turn ({detail}). The disband order releases units to "
                           "cut their upkeep.",
    "across the sea, no board": "A move needed a fleet ({detail}). The board order puts an army or "
                                "agent onto one of your fleets.",
}


def ruler_notes(findings: list[Finding], faction: str, turn: int) -> list[str]:
    """What the audit found in a ruler's own turn, told to it as facts (rulers know everything)."""
    return [RULER_WORDS.get(f.check, f.check + ": {detail}.").format(detail=f.detail)
            for f in findings if f.faction == faction and f.turn == turn and f.bin in ("ruler", "option")]


def format_audit(findings: list[Finding], title: str, only_new: set | None = None) -> str:
    """Markdown: per bin, per check, the turns it happened and one example each."""
    if only_new is not None:
        findings = [f for f in findings if f.key in only_new]
    out = [f"# Turn audit: {title}", ""]
    if not findings:
        return "\n".join(out + ["Nothing found.", ""])
    for b, heading in BINS.items():
        mine = [f for f in findings if f.bin == b]
        if not mine:
            continue
        out += [f"## {heading}", ""]
        groups = defaultdict(list)
        for f in mine:
            groups[(f.check, f.faction)].append(f)
        for (check, faction), fs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            turns = sorted({f.turn for f in fs})
            shown = ", ".join(map(str, turns[:12])) + (" ..." if len(turns) > 12 else "")
            out.append(f"- **{check}** ({faction}, {len(fs)}x, turns {shown}): {fs[-1].detail}")
        out.append("")
    return "\n".join(out)
