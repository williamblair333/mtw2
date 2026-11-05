"""The EOP coverage parser, on small inline C++ and Lua snippets."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import eop_coverage as ec  # noqa: E402

CPP = r'''
void addToLua(sol::state& luaState)
{
	/***
	Basic thing table

	@tfield int money The treasury.
	@tfield int netIncome Get only! all the sums
	@tfield int armiesNum
	@tfield getArmy getArmy
	@tfield string name

	@table thingStruct
	*/
	types.thing = luaState.new_usertype<thingStruct>("thingStruct");
	types.thing.set("money", &thingStruct::money);
	types.thing.set("netIncome", &thingStruct::netIncome);
	types.thing.set("armiesNum", &thingStruct::stackNum);
	types.thing.set("name", sol::property(&getName, &setName));
	types.thing.set("version", sol::property(&getVersion));
	types.thing.set("leader", &thingStruct::leader);
	types.thing.set("leader", &thingStruct::leader);
	/***
	Get an army using its index.
	@function thingStruct:getArmy
	@tparam int number
	@treturn armyStruct army
	*/
	types.thing.set_function("getArmy", &thingStruct::getArmy);
	types.thing.set("getStack", &thingStruct::getArmy);
	types.thing.set("note", sol::readonly(&thingStruct::note));
	types.thing.set_function("overloaded", sol::overload(
		sol::resolve<int(thingStruct*, int)>(&helpers::one),
		sol::resolve<int(thingStruct*, int, int)>(&helpers::two)
		));

	/***
	Call a function in the plugin table.
	@function M2TWEOP.doIt
	*/
	tables.M2TWEOP.set_function("doIt", &gameHelpers::doIt);

	/***
	Called when a turn starts, a faction's one.
	Exports: faction, religion

	@function onFactionTurnStart
	@tparam eventTrigger eventData
	*/

	luaState.new_enum(
		"dipRelType",
		"war", DipRelEnum::War,
		"peace", DipRelEnum::Peace
	);
}
'''

METHODS = {"thingStruct::getArmy"}


def parse():
    # tables.M2TWEOP is in TABLE_NAMES; "types.thing" is declared in the snippet
    return ec.parse_cpp(CPP, "types/thing.cpp", METHODS)


def by_name(members):
    return {m.name: m for m in members}


def test_usertype_members_and_kinds():
    members, enums, _ = parse()
    m = by_name([x for x in members if x.owner == "thingStruct"])
    assert m["money"].kind == "field" and m["money"].access == "rw"
    assert m["name"].kind == "property" and m["name"].access == "rw"
    assert m["version"].kind == "property" and m["version"].access == "ro"
    assert m["note"].kind == "field" and m["note"].access == "ro"
    assert m["getArmy"].kind == "function"
    assert m["overloaded"].kind == "function"


def test_method_pointer_in_set_is_a_function():
    members, _, _ = parse()
    m = by_name([x for x in members if x.owner == "thingStruct"])
    assert m["getStack"].kind == "function"  # `set` of &thingStruct::getArmy, a known method


def test_get_only_in_the_doc_makes_a_field_read_only():
    members, _, _ = parse()
    assert by_name(members)["netIncome"].access == "ro"


def test_duplicate_bindings_count_once():
    members, _, _ = parse()
    assert [m.name for m in members if m.owner == "thingStruct"].count("leader") == 1


def test_descriptions_from_tfield_and_function_docs():
    members, _, _ = parse()
    m = by_name([x for x in members if x.owner == "thingStruct"])
    assert m["money"].desc == "The treasury."
    assert m["getArmy"].desc == "Get an army using its index."
    assert m["money"].type == "int"


def test_global_table_functions():
    members, _, _ = parse()
    d = [m for m in members if m.owner == "M2TWEOP"]
    assert [m.name for m in d] == ["doIt"]
    assert d[0].desc == "Call a function in the plugin table."


def test_enum_values():
    _, enums, _ = parse()
    assert [(e.owner, e.name) for e in enums] == [("dipRelType", "war"), ("dipRelType", "peace")]


def test_line_numbers_point_at_the_binding():
    members, _, _ = parse()
    m = by_name(members)["money"]
    assert CPP.splitlines()[m.line - 1].strip().startswith('types.thing.set("money"')


def test_event_docs():
    events = ec.parse_events(CPP, "types/events.cpp")
    assert [e.name for e in events] == ["onFactionTurnStart"]
    assert "a faction's one" in events[0].desc and "Exports: faction, religion" in events[0].desc


def test_split_args_ignores_nested_commas():
    assert ec.split_args('"a", sol::property(&x, &y), "b, c"') == ['"a"', "sol::property(&x, &y)", '"b, c"']


# --- the Lua side ----------------------------------------------------------------------

LUA = '''
local K = {}
K.KEYS = { "farmingIncome", "taxesIncome" }

local function income(fac)
    local e = fac:getFactionEconomy(0)       -- fac.ghost is only in a comment
    local n = 0
    for _, k in ipairs(K.KEYS) do n = n + (e[k] or 0) end
    return fac.money, "fac.inString"
end

function M.report(fac)
    local s = fac:getSettlement(0)
    return { name = s.name, money = income(fac), men = s.army.numOfUnits }
end

function handlers.build(fac, o)
    local s = fac:getSettlement(0)
    s:destroyBuilding("x")
end

function M.unreached()
    local u = unit.exp
    local w = zed.name
end
'''


def lua_usage(members):
    text = ec.blank_lua(LUA)
    strings = ec.blank_lua(LUA, keep_strings=True)
    b, s = ec.split_functions(text), ec.split_functions(strings)
    ec.mark_usage(members, b, s, set())


def make(owner, name, kind="field"):
    return ec.Member(owner, name, kind, "", "", "f.cpp", 1)


def test_blank_lua_keeps_lines_and_drops_comments_and_strings():
    out = ec.blank_lua(LUA)
    assert len(out.splitlines()) == len(LUA.splitlines())
    assert "ghost" not in out and "inString" not in out
    assert "fac.inString" in ec.blank_lua(LUA, keep_strings=True)


def test_usage_roles_follow_the_call_graph():
    fac_money = make("factionStruct", "money")
    get_settlement = make("factionStruct", "getSettlement", "function")
    destroy = make("settlementStruct", "destroyBuilding", "function")
    exp = make("unit", "exp")
    ghost = make("factionStruct", "ghost")
    ms = [fac_money, get_settlement, destroy, exp, ghost]
    lua_usage(ms)
    assert fac_money.used_in == {"report"}  # `income` is reached from M.report
    assert get_settlement.used_in == {"report", "order"}
    assert destroy.used_in == {"order"}
    assert exp.used_in == {"other"}  # reached by no root
    assert not ghost.used  # a comment is not a use


def test_key_list_members_count_as_used():
    farming = make("factionEconomy", "farmingIncome")
    untouched = make("factionEconomy", "lootingIncome")
    lua_usage([farming, untouched])
    assert farming.used_in == {"report"} and not farming.ambiguous
    assert not untouched.used


def test_shared_names_use_the_receiver_to_pick_the_type():
    # `s.name` (a settlement) is certain for settlementStruct; `zed.name` is a stranger's, so every
    # other type with a `name` is a maybe
    s_name, t_name = make("settlementStruct", "name"), make("tileStruct", "name")
    lua_usage([s_name, t_name])
    assert s_name.used_in == {"report"} and not s_name.ambiguous
    assert t_name.used and t_name.ambiguous


def test_a_receiver_that_is_another_type_rules_this_one_out():
    only_settlement_reads = ec.blank_lua("function M.report(s)\n return s.name\nend\n")
    members = [make("settlementStruct", "name"), make("tileStruct", "name")]
    ec.mark_usage(members, ec.split_functions(only_settlement_reads), ec.split_functions(only_settlement_reads), set())
    assert members[0].used and not members[1].used


def test_domains_and_relevance():
    assert ec.domain_of("factionStruct") == "Faction"
    assert ec.domain_of("battleUnit") == "Battle"
    assert ec.domain_of("campaignDbRansom") == "Campaign rules database (tunables)"
    m = ec.Member("factionStruct", "setLeader", "function", "", "", "f", 1)
    m.domain = "Faction"
    assert ec.relevance_of(m) == "campaign"
    m2 = ec.Member("factionStruct", "banner", "field", "rw", "", "f", 1)
    m2.domain = "Faction"
    assert ec.relevance_of(m2) == "modding"
