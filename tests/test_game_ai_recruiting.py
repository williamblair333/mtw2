"""A ruler can switch its game AI's recruiting off: the bridge holds the realm's recruitment pools at 0
while the AI acts and gives them back before the ruler's next orders (live 11-25: France's AI trained
175 units in 43 minutes while its ruler disbanded units to pay upkeep)."""
from parley.prompt import game_recruits_line
from parley.protocol import GameAiRecruiting, GameRecruit, Orders
from parley.validate import validate_orders
from tests.test_lua_bridge import lua  # noqa: F401  (the fixture)

REALM = """
    local function pool(edu, n) return { eduIndex = edu, availablePool = n } end
    function make_fac(name, player)
        local towns = {
            { name = 'Arhus', recruitmentPoolCount = 2, pools = { pool(7, 2.5), pool(9, 0) } },
            { name = 'Paris', recruitmentPoolCount = 1, pools = { pool(7, 1) } },
        }
        for _, t in ipairs(towns) do
            t.getSettlementRecruitmentPool = function(self, j) return self.pools[j + 1] end
        end
        return { name = name, isPlayerControlled = player and 1 or 0, settlementsNum = #towns,
                 getSettlement = function(self, i) return towns[i + 1] end, towns = towns }
    end
"""


def _pools(lua):
    return [lua.eval(f"F.towns[{t}].pools[{p}].availablePool") for t, p in ((1, 1), (1, 2), (2, 1))]


def test_pools_are_held_only_when_the_ruler_switched_recruiting_off(lua):
    lua.execute(REALM + "F = make_fac('france')")
    lua.execute("BRIDGE.hold_pools(F)")
    assert _pools(lua) == [2.5, 0, 1]  # on by default: nothing held
    assert lua.eval("BRIDGE.game_ai_recruiting_order(F, { recruiting = 'off' })") is None
    lua.execute("BRIDGE.hold_pools(F)")
    assert _pools(lua) == [0, 0, 0]
    lua.execute("F.towns[1].pools[1].availablePool = 0.25")  # regrowth while held
    lua.execute("BRIDGE.release_pools(F)")
    assert _pools(lua) == [2.75, 0, 1]
    lua.execute("BRIDGE.release_pools(F)")  # once only
    assert _pools(lua) == [2.75, 0, 1]
    assert "game AI recruiting off (the ruler's order): held 3.5 units" in (lua.root / "parley_bridge.log").read_text()


def test_a_hold_that_never_emptied_its_pools_is_not_given_back_twice(lua):
    lua.execute(REALM + "F = make_fac('france'); BRIDGE.game_ai_recruiting_order(F, { recruiting = 'off' })")
    lua.execute("BRIDGE.hold_pools(F)")
    lua.execute("F.towns[1].pools[1].availablePool = 2.5; F.towns[2].pools[1].availablePool = 1")  # as if not emptied
    lua.execute("BRIDGE.release_pools(F)")
    assert _pools(lua) == [2.5, 0, 1]


def test_the_switch_is_refused_for_a_realm_with_no_game_ai(lua):
    lua.execute(REALM + "E = make_fac('england', true)")
    assert "no game AI" in lua.eval("BRIDGE.game_ai_recruiting_order(E, { recruiting = 'off' })")
    assert lua.eval("BRIDGE.ai_recruiting('england')") == "on"


def test_the_validator_refuses_the_switch_on_the_human_slot(venice_report):
    order = GameAiRecruiting(recruiting="off")
    kept, rej = validate_orders(venice_report.model_copy(update={"human_slot": True}),
                                Orders(protocol=1, game_id="test", turn=venice_report.turn, faction=venice_report.faction, orders=[order]), areas=("recruit",))
    assert not kept.orders and "no game AI" in rej[0].reason
    kept, rej = validate_orders(venice_report, Orders(protocol=1, game_id="test", turn=venice_report.turn,
                                                      faction=venice_report.faction, orders=[order]), areas=("recruit",))
    assert kept.orders == [order] and not rej


def test_the_prompt_offers_the_switch_and_says_when_it_is_off(venice_report):
    r = venice_report.model_copy(update={"game_ai_recruiting": "on",
                                         "game_recruits": [GameRecruit(unit="Pikemen", settlement="Venice")]})
    assert game_recruits_line(r).endswith('Order "game_ai_recruiting" with "recruiting": "off" to stop it.')
    off = venice_report.model_copy(update={"game_ai_recruiting": "off"})
    assert game_recruits_line(off) == "Your game AI's recruiting is off (your order): only your own recruits are trained."
