"""games/qa/envoys.toml: its instant cases run by the QA runner through the bridge's control file
against the fake game (as tests/test_qa_instant_lua.py does for instant.toml), its turn case checked
for shape, and the envoys suite's M.qa helpers and refusals on their own. The fake plays the game as
the suite guesses the real one does (a bribe or a proposal rolls its mission at once and the game's
event reports it; an island town across the sea; a fleet spawned from an admiral): not a live pass."""

import json
import tomllib
from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

from parley.qa.cases import Case, Expect, Suite
from parley.qa.runner import _required_placeholders, _run_instant_case
from tests.test_qa_instant_lua import ROBIN_IN_VENICE, TURN, TickingControl

ROOT = Path(__file__).parent.parent

# Venice's market trains diplomats and merchants (two at most); its church trains priests
EDB = """
    levels market great_market
    {
        market city requires factions { southern_european, northern_european, }
        {
            capability
            {
                agent merchant  0  requires factions { venice, milan, }
                agent diplomat  0
                agent_limit merchant 2
            }
        }
    }
    levels small_church church
    {
        small_church city requires factions { venice, }
        {
            capability
            {
                agent priest  0  requires factions { venice, milan, }
                agent_limit priest 2
            }
        }
    }
"""

# The game as the suite expects it to behave:
#   - every spawn named anew from the faction's list (live 10-30), so ids never clash
#   - an agent's bribe, bribeSettlement and marry are missions the game rolls at once and reports by
#     its own event (onBriberyMission: no chance; onMarriageMission: with one)
#   - an admiral spawned at sea is a fleet (as tests/test_qa_siege_lua.py)
#   - Corfu, Milan's island town across the sea (land 148-152 x 118-122; the fake's sea is x >= 115, y >= 90)
GAME = """
FAKE.spawn_ignores_names = true
FAKE.edu[32] = { index = 32, eduType = 'cog' }
local spawned = 0
local function missions(c)
    local fac = c._fac
    c.bribe = function(self, target)
        table.insert(FAKE.calls, 'bribe ' .. self.namedCharacter.fullName .. ' ' .. target.namedCharacter.fullName)
        BRIDGE.on_agent_mission('bribery', { character = self, faction = fac, missionSuccessLevel = 'storm' }, false)
    end
    c.bribeSettlement = function(self, s)
        table.insert(FAKE.calls, 'bribeSettlement ' .. self.namedCharacter.fullName .. ' ' .. s.name)
        BRIDGE.on_agent_mission('bribery', { character = self, faction = fac, missionSuccessLevel = 'earthquake' }, false)
    end
    c.marry = function(self, target)
        table.insert(FAKE.calls, 'marry ' .. self.namedCharacter.fullName .. ' ' .. target.namedCharacter.fullName)
        BRIDGE.on_agent_mission('marriage proposal', { character = self, faction = fac,
            missionSuccessLevel = 'horde', missionProbability = 35 }, true)
    end
end
for _, f in ipairs(FAKE.factions) do
    local create, army = f.createCharacter, f.spawnArmy
    f.createCharacter = function(...)
        spawned = spawned + 1
        FAKE.random_name = 'Spawn' .. spawned
        local c = create(...)
        missions(c)
        return c
    end
    f.spawnArmy = function(self, gname, n2, ctype, label, portrait, x, y, ...)
        spawned = spawned + 1
        FAKE.random_name = 'Spawn' .. spawned
        if ctype == 3 then
            table.insert(FAKE.calls, 'spawn fleet ' .. x .. ' ' .. y)
            return FAKE.add_fleet(self, FAKE.random_name, x, y)
        end
        return army(self, gname, n2, ctype, label, portrait, x, y, ...)
    end
end
local getTile = FAKE.stratMap.getTile
FAKE.stratMap.getTile = function(x, y)
    local t = getTile(x, y)
    if x >= 148 and x <= 152 and y >= 118 and y <= 122 then t.isLand = 1 end
    return t
end
local corfu = { name = 'Corfu', localizedName = 'Corfu', ownerFaction = FAKE.byName.milan, xCoord = 150,
                yCoord = 120, regionID = 14, army = { numOfUnits = 1 } }
FAKE.settlements.Corfu = corfu
FAKE.regionSettlements[14] = corfu
FAKE.stratMap.regionsNum = 15
-- marry: the game proposes only between real family members (live 11-04), so the bench's own: a
-- princess of Venice's family, and an unmarried Milanese family general of age (Milan is at peace
-- with Venice; HRE stays the enemy other cases need)
local agnese = FAKE.add_character(FAKE.byName.venice, 'Agnese', 'princess', 118, 84)
agnese.namedCharacter.isFamily, agnese.namedCharacter.age = 1, 19
missions(agnese)
FAKE.add_army(FAKE.byName.milan, 'Konrad', 126, 78)
local milan = FAKE.byName.milan
local konrad = milan:getCharacter(milan.numOfCharacters - 1)
konrad.namedCharacter.isFamily, konrad.namedCharacter.age = 1, 24
"""


@pytest.fixture
def game(tmp_path):
    rt = LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f"package.path = '{ROOT}/lua/?.lua;{ROOT}/lua/vendor/?.lua;{ROOT}/tests/lua/?.lua;' .. package.path")
    rt.execute("FAKE = require('fake_game'); FAKE.reset()")
    root = tmp_path / "parley_turns"
    for turn in (TURN - 1, TURN):
        (root / "g1" / f"turn-{turn:04d}" / "venice").mkdir(parents=True)
    # control "full", as write_qa_config gives the bench's seat: recruiting is the "recruit" area
    (root / "bridge.txt").write_text("game_id=g1\nfaction=venice\nautoplay=1\nautoplay_wait=60\n"
                                     "control=venice:diplomacy,armies,agents,build,recruit,taxes\n")
    edb = tmp_path / "data" / "export_descr_buildings.txt"
    edb.parent.mkdir(parents=True)
    edb.write_text(EDB)
    rt.execute(f"BRIDGE = require('parley_bridge'); BRIDGE.setup('{root}'); "
               "BRIDGE.clock = function() return FAKE.now end")
    rt.execute(ROBIN_IN_VENICE)
    rt.execute(GAME)
    rt.execute("FAKE.ui.end_turn = { elementName = 'end_turn', "
               "execute = function() FAKE.calls[#FAKE.calls + 1] = 'press end_turn' end }")
    (root / "g1" / f"turn-{TURN:04d}" / "venice" / "state.json").write_text(
        '{"turn": 3, "faction": "venice", "settlements": [{"id": "Venice", "x": 120, "y": 88}], '
        '"armies": [{"id": "garrison:Venice", "in_settlement": "Venice", "leader": "Captain Robin"}]}'
    )
    return rt, root


def test_only_a_real_family_bachelor_is_a_suitor(game):
    # live 11-04: the game ran no proposal to a spawned general (isFamily false), 11 runs in a row
    rt, _ = game
    assert rt.eval("BRIDGE.qa.wooer('venice')") == "venice"
    assert rt.eval("BRIDGE.qa.princess('venice')") == "Agnese"
    rt.execute("local m = FAKE.byName.milan; m:getCharacter(m.numOfCharacters - 1).namedCharacter.isFamily = 0")
    assert rt.eval("BRIDGE.qa.wooer('venice')") is None
    rt.execute("local m = FAKE.byName.milan; local nc = m:getCharacter(m.numOfCharacters - 1).namedCharacter; "
               "nc.isFamily = 1; nc.spouse = { fullName = 'Bianca' }")
    assert rt.eval("BRIDGE.qa.wooer('venice')") is None


def _suite() -> Suite:
    """envoys.toml as written, with the fake's faction for England (in its log lines too)."""
    text = (ROOT / "games" / "qa" / "envoys.toml").read_text(encoding="utf-8")
    return Suite.model_validate(tomllib.loads(text.replace("england", "venice")))


def _calls(rt) -> list[str]:
    return list(rt.eval("FAKE.calls").values())


INSTANT = {
    "recruit_diplomat", "recruit_merchant", "recruit_princess_refused", "recruit_merchant_limit_refused",
    "move_agent_walks", "move_agent_into_foreign_town_refused", "move_agent_across_sea_refused",
    "bribe_army", "bribe_agent", "marry_foreign_general", "agent_order_naming_a_general_refused",
    "bribe_settlement",
}


def test_the_envoys_suite_s_instant_cases_run_on_the_fake_game_in_one_held_turn(game):
    rt, root = game
    ctrl = TickingControl(rt, root)
    results = {}
    for case in (c for c in _suite().cases if c.kind == "instant"):
        res, _ = _run_instant_case(case, "qa-envoys", "g1", "venice", root, ctrl, TURN,
                                   poll_interval=0.0, turn_wait=1.0)
        results[case.name] = res
        assert not (root / "paused.txt").exists()

    assert set(results) == INSTANT
    failed = {name: (res.outcome, res.evidence) for name, res in results.items() if res.outcome != "pass"}
    assert not failed, failed
    calls = _calls(rt)
    assert "press end_turn" not in calls
    # each mission reached the game, against what the case set up
    assert any(c.startswith("bribe ") for c in calls) and any(c.startswith("marry ") for c in calls)
    assert any(c.startswith("bribeSettlement ") and c.endswith(" Innsbruck") for c in calls)
    assert any(c.startswith("spawn fleet ") for c in calls)
    log = (root / "parley_bridge.log").read_text()
    # the mission lines themselves (the marry case's M.qa.news reads echo the news into the log)
    assert sum(1 for ln in log.splitlines() if "agent mission: " in ln and "'s bribery: " in ln) == 3
    assert "'s marriage proposal: partly successful (chance was 35%)" in log
    # the recruits paid for are queued for the next turn; the princess and the limit paid nothing
    queued = json.loads((root / "g1" / "training.json").read_text())
    assert sorted(t["agent"] for t in queued) == ["diplomat", "merchant"]


def test_a_game_with_no_town_that_trains_merchants_skips_the_merchant_recruit(game):
    rt, root = game
    rt.execute("FAKE.settlements.Venice.getBuilding = function() return nil end; FAKE.settlements.Venice.buildingsNum = 0")
    case = next(c for c in _suite().cases if c.name == "recruit_merchant")
    res, _ = _run_instant_case(case, "qa-envoys", "g1", "venice", root, TickingControl(rt, root), TURN,
                               poll_interval=0.0, turn_wait=1.0)
    assert res.outcome == "inconclusive", res.evidence
    assert "'none'" in res.evidence


def test_a_princess_disgraced_by_a_refusal_reaches_the_news_and_passes_the_case(game):
    # live 11-04/11-05 (4 of 4): a hard refusal fires no mission event and the game removes the
    # princess ("Princess Disgraced!"); her record says dead. The ruler must hear of it.
    rt, root = game
    rt.execute("local ven = FAKE.byName.venice\n"
               "local agnese\n"
               "for _, c in ipairs(ven.characters) do if c.namedCharacter.fullName == 'Agnese' then agnese = c end end\n"
               "agnese.marry = function(self, target)\n"
               "  table.insert(FAKE.calls, 'marry Agnese ' .. target.namedCharacter.fullName)\n"
               "  agnese.namedCharacter.isAlive = function() return 0 end\n"
               "end\n"
               "ven.named = { agnese.namedCharacter }; ven.numOfNamedCharacters = 1")
    case = next(c for c in _suite().cases if c.name == "marry_foreign_general")
    res, _ = _run_instant_case(case, "qa-envoys", "g1", "venice", root, TickingControl(rt, root), TURN,
                               poll_interval=0.0, turn_wait=1.0)
    assert res.outcome == "pass", res.evidence
    assert "marry Agnese Konrad" in _calls(rt)
    news = rt.eval("BRIDGE.take_agent_news('venice')")
    assert list(news.values()) == ["Agnese's marriage proposal: rejected, and she was disgraced and removed (to Konrad)"]


def test_a_proposal_answered_by_its_mission_is_not_reported_twice(game):
    rt, _ = game
    rt.execute("local ven = FAKE.byName.venice; ven.named = {}; ven.numOfNamedCharacters = 0")
    rt.eval("BRIDGE.note_proposal('venice', 'Agnese', 'Konrad')")
    rt.execute("BRIDGE.on_agent_mission('marriage proposal', { faction = FAKE.byName.venice, "
               "missionSuccessLevel = 'storm', character = { fullName = 'Agnese' } }, false)")
    assert list(rt.eval("BRIDGE.take_agent_news('venice')").values()) == ["Agnese's marriage proposal: highly successful"]


@pytest.mark.parametrize("who", ["Agnese_(null)", None])  # a raw name; a read that failed ("a princess")
def test_a_mission_line_naming_her_oddly_still_settles_the_proposal(game, who):
    # review 11-05: a married princess is off the map when her event comes; her proposal must not
    # be left pending to read as a disgrace once her record says dead
    rt, _ = game
    rt.execute("local ven = FAKE.byName.venice; ven.named = { { fullName = 'Agnese', "
               "isAlive = function() return 0 end } }; ven.numOfNamedCharacters = 1")
    rt.eval("BRIDGE.note_proposal('venice', 'Agnese', 'Konrad')")
    char = f"{{ fullName = '{who}' }}" if who else "nil"
    rt.execute("BRIDGE.on_agent_mission('marriage proposal', { faction = FAKE.byName.venice, "
               f"missionSuccessLevel = 'storm', character = {char} }}, false)")
    news = list(rt.eval("BRIDGE.take_agent_news('venice')").values())
    assert len(news) == 1 and news[0].endswith("'s marriage proposal: highly successful"), news


def test_a_bribe_the_game_never_reports_fails_the_case(game):
    # the order taken but no mission line: not a pass (the line is the only evidence it happened)
    rt, root = game
    rt.execute("for _, f in ipairs(FAKE.factions) do local create = f.createCharacter; "
               "f.createCharacter = function(...) local c = create(...); "
               "c.bribe = function() end; return c end end")
    case = next(c for c in _suite().cases if c.name == "bribe_army")
    case = case.model_copy(update={"expect": [case.expect[0], case.expect[1].model_copy(update={"within": 0.2})]})
    res, _ = _run_instant_case(case, "qa-envoys", "g1", "venice", root, TickingControl(rt, root), TURN,
                               poll_interval=0.0, turn_wait=1.0)
    assert res.outcome == "fail", res.evidence
    assert "bribery" in res.evidence and "not seen within 0.2 s" in res.evidence


def test_the_turn_case_groups_what_needs_a_turn_and_names_only_what_it_binds():
    text = (ROOT / "games" / "qa" / "envoys.toml").read_text(encoding="utf-8")
    suite = Suite.model_validate(tomllib.loads(text))
    assert {c.name for c in suite.cases if c.kind == "instant"} == INSTANT
    turn = [c for c in suite.cases if c.kind == "turn"]
    assert [c.name for c in turn] == ["next_turn_recruit_and_trade"] and suite.cases[-1] is turn[0]
    names = [c.name for c in suite.cases]
    assert names.index("recruit_merchant") < names.index("recruit_merchant_limit_refused")
    assert names[-2] == "bribe_settlement"  # last of the instant cases: a bribe that works takes the town
    live = {"garrison_town", "garrison_town_x", "garrison_town_y"}
    for case in suite.cases:
        assert _required_placeholders(case) - case.binds <= live, case.name
    case = turn[0]
    assert [o["type"] for o in case.orders[1]] == ["recruit_agent"]
    assert "drop_training" in str(case.setup[0])  # the instant cases' recruits don't arrive with the seat's
    assert any(e.state == "income_parts.merchants" for e in case.expect)
    assert "What can't be forced" in text and "Unproven live" in text


def test_within_polls_a_log_line_in_an_instant_case_only():
    assert Expect(log="x", within=30).within == 30
    with pytest.raises(ValueError, match="within goes with a lua query or a log line"):
        Expect(state="treasury", equals=1, within=5)
    with pytest.raises(ValueError, match='within are for kind = "instant"'):
        Case(name="x", expect=[Expect(log="x", within=5)])


@pytest.fixture
def lua(game):
    rt, root = game

    def run(line: str):
        return rt.eval(f"(function() {line} end)()")

    rt.execute("M = BRIDGE")
    run.root = root
    return run


def test_an_agent_order_naming_a_general_says_he_is_one_and_what_to_use(lua):
    move = lua('return M.qa.order("venice", { type = "move_agent", agent = "Doge Enrico", x = 118, y = 85 })')
    assert move == ("move_agent refused: unknown agent 'Doge Enrico': Doge Enrico is one of your generals, not an "
                    'agent; move his army with {"type": "move_army", "army": "Doge Enrico", "x": 118, "y": 85}')
    assert lua('return M.qa.order("venice", { type = "marry", agent = "Doge Enrico", target = "Heinrich" })') == (
        "marry refused: unknown agent 'Doge Enrico': Doge Enrico is one of your generals, not an agent; "
        "a marry order is for a princess of yours")
    assert lua('return M.qa.order("venice", { type = "spy", agent = "Doge Enrico", target = "Innsbruck" })').endswith(
        "not an agent; a spy order is for a spy of yours")
    # a name that is nobody of Venice's stays as it was
    assert lua('return M.qa.order("venice", { type = "bribe", agent = "Ulrich", target = "Innsbruck" })') == (
        "bribe refused: unknown agent 'Ulrich' (not one of yours)")
    assert not any(c.startswith("moveToTile") for c in lua("return FAKE.calls").values())


def test_the_audit_still_reads_the_general_s_refusal_as_the_ruler_s_mistake():
    from parley.audit import UNKNOWN
    reason = ("unknown agent 'Doge Enrico': Doge Enrico is one of your generals, not an agent; move his army "
              'with {"type": "move_army", "army": "Doge Enrico", "x": 118, "y": 85}')
    assert UNKNOWN.search(reason).group(1) == "Doge Enrico"


def test_agents_counts_and_agent_town_follow_the_edb(lua):
    assert lua('return M.qa.agents("venice", "merchant")') == "have=0 limit=2"
    assert lua('return M.qa.agents("venice", "diplomat")') == "have=1 limit=none"  # Pietro; no limit
    assert lua('return M.qa.agent_town("venice", "merchant")') == "Venice"
    assert lua('return M.qa.agent_town("venice", "assassin")') == "none"  # no building trains one
    assert lua('return M.qa.agents("venice", "princess")') is None  # not recruitable


def test_fill_agents_spawns_up_to_the_limit_and_says_unlimited(lua):
    assert lua('return M.qa.fill_agents("venice", "merchant", 120, 88)') == "have=2 limit=2"
    assert lua('return M.qa.agent_town("venice", "merchant")') == "none"
    assert lua('return M.qa.fill_agents("venice", "diplomat", 120, 88)') == "unlimited"
    made = [c for c in lua("return FAKE.calls").values() if c.startswith("createCharacter venice merchant")]
    assert len(made) == 2


def test_funds_only_raises_the_treasury(lua):
    assert lua('return M.qa.funds("venice", 50000)') == 50000
    assert lua('return M.qa.funds("venice", 100)') == 50000


def test_resource_finds_the_nearest_free_one_walkable(lua):
    lua("local get = FAKE.stratMap.getRegion; FAKE.stratMap.getRegion = function(id) local r = get(id); "
        "if id == 10 then r.resourcesNum = 3; r.getResource = function(self, j) return ({ "
        "{ xCoord = 120, yCoord = 87 }, { xCoord = 116, yCoord = 85 }, { xCoord = 150, yCoord = 121 } })[j + 1] end end; "
        "return r end")
    # (120,87) has Marco on it; (150,121) is on Corfu's island, across the sea
    assert lua("return M.qa.resource(120, 88, 0, 40)") == "116,85"
    assert lua("return M.qa.resource(120, 88, 0, 2)") is None


def test_drop_training_drops_only_the_faction_s_queued_recruits(lua):
    path = lua.root / "g1" / "training.json"
    path.write_text(json.dumps([{"faction": "venice", "settlement": "Venice", "agent": "diplomat", "ready": 4},
                                {"faction": "milan", "settlement": "Milan", "agent": "spy", "ready": 4}]))
    assert lua('return M.qa.drop_training("venice")') == 0 + 1
    assert [t["faction"] for t in json.loads(path.read_text())] == ["milan"]
    assert lua('return M.qa.drop_training("venice")') == 0


def test_merchant_income_reads_the_economy(lua):
    assert lua('return M.qa.merchant_income("venice")') == 0
    lua("FAKE.byName.venice.getFactionEconomy = function() return { merchantIncome = 212.6 } end")
    assert lua('return M.qa.merchant_income("venice")') == 212
