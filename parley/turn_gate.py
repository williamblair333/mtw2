"""Turn gate: determine whether a ruler's turn is quiet enough for a cheap brain.

A quiet turn has no urgent events, enemy threats, diplomacy, popups, or financial
crisis, and falls between cadence turns and max quiet streaks.
"""

from __future__ import annotations

from parley.protocol import StateReport


def quiet_turn(
    report: StateReport,
    *,
    events: list[str],
    diplomacy: list,
    game_messages: list | None,
    quiet_streak: int,
    cadence: int = 5,
    max_streak: int = 2,
) -> str:
    """Return "" when the turn is quiet, else the first reason it is not."""
    # 1. messages
    if diplomacy or game_messages:
        return "messages"

    # 2. popups / character events / news / stance changes / agent results
    if report.popups:
        return "popups"
    if report.character_events:
        return "character events"
    if report.news:
        return "news"
    if report.stance_changes:
        return "stance changes"
    if report.agent_results:
        return "agent results"

    # 3. events (diff vs last turn)
    if events:
        return "events"

    # 4. enemy near: visible enemy army at war within 8 Chebyshev tiles of settlement or army
    war_factions = {
        f.id for f in report.factions if f.stance == "war"
    } | {
        f.name for f in report.factions if f.stance == "war"
    }
    for enemy in report.visible_enemies:
        if enemy.faction and enemy.faction in war_factions:
            for s in report.settlements:
                if s.x is not None and s.y is not None:
                    if max(abs(enemy.x - s.x), abs(enemy.y - s.y)) <= 8:
                        return "enemy near"
            for a in report.armies:
                if max(abs(enemy.x - a.x), abs(enemy.y - a.y)) <= 8:
                    return "enemy near"

    # 5. siege: own settlement under siege (Army has no besieging field; skipped)
    if any(s.siege is not None for s in report.settlements):
        return "siege"

    # 6. money: treasury < 0 or income < 0
    if report.treasury < 0 or report.income < 0:
        return "money"

    # 7. cadence
    if cadence > 0 and report.turn % cadence == 0:
        return "cadence"

    # 8. streak
    if quiet_streak >= max_streak:
        return "streak"

    return ""
