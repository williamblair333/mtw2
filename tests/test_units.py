"""The unit table (from the game's unit file) and the free-upkeep slot rule."""

from parley import units
from parley.protocol import Settlement, Training, Unit


def _city(buildings, **kw):
    return Settlement(id="London", name="London", region="R", garrison_strength=1, population=1,
                      buildings=buildings, **kw)


def test_table_uses_the_names_the_recruit_lists_use():
    for name in ("Town Militia", "Spear Militia", "Peasants", "Levy Spearmen", "cog", "NE Ballista",
                 "Mailed Knights", "Dismounted Feudal Knights"):
        assert units.info(name) is not None, name


def test_table_facts_match_the_unit_file():
    tm = units.info("Town Militia")
    assert (tm["men"], tm["cost"], tm["upkeep"], tm["free_upkeep"]) == (60, 290, 125, True)
    assert not units.is_free("Peasants") and units.info("Peasants")["upkeep"] == 90
    assert units.info("cog")["role"] == "ship" and units.info("NE Ballista")["role"] == "siege"
    assert units.info("Peasant Archers")["role"] == "missile"
    assert units.info("Mailed Knights")["role"] == "cavalry"
    assert sum(u["free_upkeep"] for u in units.table().values()) >= 30


def test_garrison_kind_excludes_ships_and_siege_only():
    assert not units.is_garrison_kind("cog") and not units.is_garrison_kind("NE Ballista")
    assert units.is_garrison_kind("Peasants") and units.is_garrison_kind("Not In The Table")


def test_free_slots_by_wall_level_and_castle():
    walls = {"wooden_pallisade": 2, "wooden_wall": 3, "stone_wall": 4, "large_stone_wall": 5,
             "huge_stone_wall": 6}
    for b, n in walls.items():
        assert units.free_slots(["market", b]) == n
    assert units.free_slots(["fortress", "barracks"]) == 0
    assert units.free_slots(["fortress", "tourney_fields"]) == 1
    assert units.free_slots([]) == 0


def test_slots_left_counts_garrison_training_and_queue():
    s = _city(["stone_wall"], training=[Training(unit="Town Militia", ready_turn=5)],
              recruit_queue=["Spear Militia (2 turns left)", "Peasants (1 turn left)"])
    held = [Unit(type="Town Militia", soldiers=60), Unit(type="Peasants", soldiers=60)]
    assert units.free_slots_left(s, held) == 4 - 3  # militia held + training + queued; Peasants aren't free
    assert units.free_slots_left(_city(["wooden_wall"]), [Unit(type="Town Militia", soldiers=1)] * 9) == 0


def test_defence_value_formula():
    # Town Militia: 60 men * (defence 1 + armour 0 + shield 6) / upkeep 125
    assert abs(units.defence_value("Town Militia") - 60 * 7 / 125) < 1e-9
    assert units.defence_value("Town Militia", upkeep=1) == 420
    assert units.defence_value("Nope") == 0
