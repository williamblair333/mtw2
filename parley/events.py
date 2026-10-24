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
    new_armies = {a.id for a in after.armies}
    events += [f"Your army {a.leader or a.id} is gone (destroyed, disbanded or merged)."
               for a in before.armies if a.leader and a.id not in new_armies]
    if after.treasury != before.treasury:
        delta = after.treasury - before.treasury
        events.append(f"Treasury: {before.treasury} → {after.treasury} ({delta:+d}).")
    return events
