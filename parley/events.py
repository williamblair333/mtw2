"""What changed for a ruler since its last report: wars, lost or gained settlements, armies
that vanished, gold that moved. Covers the game's own AI factions too, since it reads the
world as the game reports it."""

from parley.protocol import StateReport


def diff_reports(before: StateReport | None, after: StateReport) -> list[str]:
    if before is None:
        return []
    events = []
    old_stance = {f.id: f.stance for f in before.factions}
    for f in after.factions:
        was = old_stance.get(f.id)
        if was is not None and was != f.stance:
            events.append(f"{f.name} ({f.id}): now at {f.stance} with you (was {was})."
                          if f.stance == "war" else
                          f"{f.name} ({f.id}): now {f.stance} with you (was {was}).")
    old_s = {s.id: s.name for s in before.settlements}
    new_s = {s.id: s.name for s in after.settlements}
    events += [f"You lost {old_s[s]}." for s in sorted(old_s.keys() - new_s.keys())]
    events += [f"You gained {new_s[s]}." for s in sorted(new_s.keys() - old_s.keys())]
    new_armies = {_base(a.id) for a in after.armies}  # (ids lost " (null)" once: not a loss)
    events += [f"Your army {a.leader or a.id} is gone (destroyed, disbanded or merged)."
               for a in before.armies if a.leader and _base(a.id) not in new_armies]
    if after.treasury != before.treasury:
        delta = after.treasury - before.treasury
        events.append(f"Treasury: {before.treasury} → {after.treasury} ({delta:+d}).")
    return events + works(before, after) + changed_hands(before, after) + losses(before, after)


def works(before: StateReport, after: StateReport) -> list[str]:
    """Buildings finished or gone, and recruits who joined, in settlements held both turns
    (live, Scratch: "Caernarvon's church: check whether it finished")."""
    was = {s.id: s for s in before.settlements}
    events = []
    for s in after.settlements:
        old = was.get(s.id)
        if old is None:
            continue
        built = [b for b in s.buildings if b not in old.buildings]
        gone = [b for b in old.buildings if b not in s.buildings]
        if len(built) > 2:  # a settlement finishes one building a turn: more means the names changed
            continue
        if len(built) == 1 and len(gone) == 1:  # an upgrade replaces the level below it
            events.append(f"{s.name}: {built[0]} finished, replacing {gone[0]}.")
        else:
            events += [f"{s.name}: {b} finished." for b in built]
            events += [f"{s.name}: {b} no longer stands (destroyed or replaced)." for b in gone]
        done = list(old.training)
        for t in s.training:
            match = next((d for d in done if d.unit == t.unit), None)
            if match:
                done.remove(match)
        events += [f"{s.name}: {t.unit} finished training and joined the garrison."
                   if t.ready_turn <= after.turn else f"{s.name}: {t.unit} left the training queue unfinished."
                   for t in done]
    return events


def changed_hands(before: StateReport, after: StateReport) -> list[str]:
    """Foreign settlements in sight both turns that now belong to someone else."""
    was = {s.id: s.faction for s in before.nearby_settlements}
    return [f"{s.name} changed hands: {was[s.id]} → {s.faction}." for s in after.nearby_settlements
            if s.id in was and was[s.id] != s.faction]


NEAR = 6  # tiles: a foreign assassin this close to someone last turn is evidence


def _base(agent_id: str) -> str:
    """An agent's id as the family records name him: no #2, no " (null)", spaces for _."""
    return agent_id.split("#")[0].removesuffix(" (null)").replace("_", " ")


def losses(before: StateReport, after: StateReport) -> list[str]:
    """Agents and family who were there last turn and are gone or dead now, each with the
    plausible causes ordered by the evidence, and a request to theorize."""
    # an empty roster after a full one is a failed read in the bridge, not a massacre
    family_read = bool(after.family) or not before.family
    was = {p.name: p for p in before.family if p.alive} if family_read else {}
    now = {p.name: p for p in after.family}
    agents_now = {_base(a.id) for a in after.agents}
    gone = []
    for a in before.agents:
        name = _base(a.id)
        if name not in agents_now and not (name in now and now[name].alive):
            gone.append((name, a.kind, (a.x, a.y)))
    named = {g[0] for g in gone}
    for name, p in was.items():
        if name not in named and (name not in now or not now[name].alive):
            gone.append((name, p.kind, None))
    out = []
    for name, kind, pos in gone:
        wed = _married_as(name, was.get(name), before, after)
        out.append(f"{name} married {wed.spouse} and now goes by {wed.name}." if wed
                   else _loss(name, kind, pos, before, after))
    return out


def _married_as(name: str, was, before: StateReport, after: StateReport):
    """A woman of the family who married and took her husband's house name: alive under the same
    first name, with the same parent, as someone nobody had last turn (live: Crystina of Lydham
    became Crystina of Cantebury, and the ruler mourned her as an assassin's victim)."""
    first, parent = name.split()[0], was.parent if was else None
    old = {p.name for p in before.family}
    for p in after.family:
        if (p.alive and p.spouse and p.name not in old and p.name.split()[0] == first
                and (parent is None or p.parent == parent)):
            return p
    return None


def _loss(name: str, kind: str | None, pos, before: StateReport, after: StateReport) -> str:
    old = next((p for p in before.family if p.name == name), None)
    new = next((p for p in after.family if p.name == name), None)
    kind = kind or (old.kind if old else None)
    age = new.age if new and new.age is not None else (old.age if old else None)
    who = f"{name} ({', '.join(w for w in (kind, f'aged {age}' if age is not None else None) if w)})"
    if new and new.now_serves:
        return (f"{who} has left your service: the game lists them alive, now serving "
                f"{new.now_serves}. A general who goes over may have deserted to the rebels or been "
                "bribed; an agent may have been bribed away. Weigh why, write your theory in your "
                "note, and decide what to do about it.")
    if new and not new.alive:
        fate = "The game's records list them as dead."
    elif new is None and old is not None:
        fate = "They are no longer in your family's records."
    else:
        fate = "They are no longer among your agents."
    causes: list[tuple[int, str]] = []
    told = [e for e in after.character_events if e.startswith(name)]
    for e in told:
        causes.append((5, f"the game reports that {e}"))
    turned = [a for a in after.seen_agents if _base(a.id) == name and a.faction != after.faction]
    if turned:
        causes.append((4, f"bribed or married away: someone named {name} now serves {turned[0].faction}"))
    if kind == "princess" or (old and old.kind == "princess"):
        causes.append((2, "married into another house (the game usually announces it; check the "
                          "game messages)"))
    if pos:
        near = [a for a in before.seen_agents if a.kind == "assassin"
                and max(abs(a.x - pos[0]), abs(a.y - pos[1])) <= NEAR]
        if near:
            causes.append((3, "assassination: " + "; ".join(
                f"{a.faction}'s assassin {a.id} stood {max(abs(a.x - pos[0]), abs(a.y - pos[1]))} "
                "tiles away last turn" for a in near)))
    if not any(c.startswith("assassination") for _, c in causes):
        enemies = sorted({a.faction for a in before.seen_agents if a.kind == "assassin" and a.faction})
        causes.append((1, "assassination: " + (f"assassins of {', '.join(enemies)} were in sight last turn"
                                               if enemies else "no enemy assassin was seen, which "
                                               "doesn't rule one out")))
    if kind in ("spy", "assassin", "diplomat"):
        failed = [r for r in after.agent_results if r.startswith(name) and "not successful" in r]
        if failed:
            causes.append((3, f"caught on a failed mission ({failed[0]}); spies and assassins can "
                              "be executed when caught"))
    if age is not None:
        causes.append((3 if age >= 60 else 2 if age >= 50 else 0,
                       f"old age or illness at {age}" + (" (unlikely so young)" if age < 50 else "")))
    if kind == "general" or (old and old.kind == "general"):
        gone_armies = {a.id for a in before.armies} - {a.id for a in after.armies}
        if gone_armies:
            causes.append((2, f"killed in battle: your army {', '.join(sorted(gone_armies))} is gone too"))
    causes.append((0, "plague (the game doesn't report it per person)"))
    causes.sort(key=lambda c: -c[0])
    listed = "; ".join(f"{i}) {c}" for i, (_, c) in enumerate(causes, 1))
    return (f"{who} is gone since your last turn. {fate} Plausible causes, likeliest first by the "
            f"evidence: {listed}. Weigh who gained from it, write your theory in your note, and "
            "decide what to do about it.")
