import pytest
from tests.test_lua_bridge import autoplay, lua, start_turn


def _setup_m2tw(lua):
    lua.execute("""
        DISASTERS = {}
        DECISIONS = {}
        M2TW = {
            campaign = {
                execScriptEvent = function(a, kind, x, y, n, b)
                    DISASTERS[#DISASTERS + 1] = { a = a, kind = kind, x = x, y = y, n = n, b = b }
                end,
                historicEvent = function(event_id, title, desc, opt)
                    DECISIONS[#DECISIONS + 1] = { event_id = event_id, title = title, desc = desc, opt = opt }
                end,
            }
        }
    """)


@pytest.mark.parametrize("kind", ["earthquake", "flood", "storm", "famine", "plague", "riot", "fire"])
def test_force_disaster_valid(lua, kind):
    _setup_m2tw(lua)
    res = lua.eval(f"BRIDGE.qa.force_disaster('{kind}', 110, 154)")
    assert res == kind
    calls = list(lua.eval("DISASTERS").values())
    assert len(calls) == 1
    c = calls[0]
    assert c["a"] == ""
    assert c["kind"] == kind
    assert c["x"] == 110
    assert c["y"] == 154
    assert c["n"] == 1
    assert c["b"] == ""
    log = (lua.root / "parley_bridge.log").read_text()
    assert f"qa: force_disaster ok: {kind}" in log


def test_force_disaster_unknown_kind_refused_and_calls_nothing(lua):
    _setup_m2tw(lua)
    res = lua.eval("BRIDGE.qa.force_disaster('tornado', 110, 154)")
    assert res is None
    calls = list(lua.eval("DISASTERS").values())
    assert len(calls) == 0
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_disaster failed: " in log
    assert "unknown disaster kind 'tornado'" in log


def test_force_rebellion_uses_the_games_script_command(lua):
    lua.execute("""
        SENT = {}
        M2TWEOP.scriptCommand = function(cmd, args) SENT[#SENT + 1] = cmd .. " " .. args end
    """)
    res = lua.eval("BRIDGE.qa.force_rebellion('Venice')")
    assert res == "Venice"
    assert list(lua.eval("SENT").values()) == ["provoke_rebellion Venice"]
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_rebellion ok: Venice" in log


def test_force_rebellion_unknown_settlement_refused(lua):
    res = lua.eval("BRIDGE.qa.force_rebellion('NonexistentCity')")
    assert res is None
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_rebellion failed: " in log
    assert "unknown settlement 'NonexistentCity'" in log


def test_force_leader_death_kills_character_and_returns_name(lua):
    lua.execute("""
        KILLED = {}
        local c = {
            kill = function(self) table.insert(KILLED, "killed") end,
        }
        local rec = {
            fullName = "King Henry",
            character = c,
        }
        FAKE.byName.venice.leader = rec
    """)
    res = lua.eval("BRIDGE.qa.force_leader_death('venice')")
    assert res == "King Henry"
    assert list(lua.eval("KILLED").values()) == ["killed"]
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_leader_death ok: King Henry" in log


def test_force_leader_death_errors_when_no_character_on_map(lua):
    lua.execute("""
        local rec = {
            fullName = "Ghost King",
            character = nil,
        }
        FAKE.byName.venice.leader = rec
    """)
    res = lua.eval("BRIDGE.qa.force_leader_death('venice')")
    assert res is None
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_leader_death failed: " in log
    assert "has no character on the map" in log


def test_force_decision_calls_historic_event(lua):
    _setup_m2tw(lua)
    res = lua.eval("BRIDGE.qa.force_decision('Forced Event Title')")
    assert res == "Forced Event Title"
    calls = list(lua.eval("DECISIONS").values())
    assert len(calls) == 1
    c = calls[0]
    assert c["event_id"] == "qa_forced_decision"
    assert c["title"] == "Forced Event Title"
    assert c["desc"] == "Forced by the QA bench."
    assert c["opt"] is True
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_decision ok: Forced Event Title" in log


def test_force_crusade_calls_start_with_expected_args(lua):
    lua.execute("""
        CRUSADE_CALLS = {}
        M2TW = {
            campaign = {
                crusade = {
                    start = function(self, s, time_to_join, caller)
                        CRUSADE_CALLS[#CRUSADE_CALLS + 1] = {
                            settlement = s.name,
                            time_to_join = time_to_join,
                            caller = caller,
                        }
                    end
                }
            }
        }
    """)
    res = lua.eval("BRIDGE.qa.force_crusade('Venice')")
    assert res == "Venice"
    calls = list(lua.eval("CRUSADE_CALLS").values())
    assert len(calls) == 1
    assert calls[0]["settlement"] == "Venice"
    assert calls[0]["time_to_join"] == 10
    assert calls[0]["caller"] is None
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_crusade ok: Venice" in log


def test_force_crusade_unknown_settlement_reports_failure(lua):
    lua.execute("""
        M2TW = { campaign = { crusade = { start = function() end } } }
    """)
    res = lua.eval("BRIDGE.qa.force_crusade('NonexistentCity')")
    assert res is None
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_crusade failed: " in log
    assert "unknown settlement 'NonexistentCity'" in log


def test_force_crusade_no_crusade_struct_reports_failure(lua):
    lua.execute("M2TW = { campaign = {} }")
    res = lua.eval("BRIDGE.qa.force_crusade('Venice')")
    assert res is None
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_crusade failed: " in log
    assert "no crusade struct" in log


def test_force_ai_attack_calls_attack_army_with_expected_args(lua):
    target_id = lua.eval("BRIDGE.qa.spawn_army('venice', 110, 70)")
    assert target_id is not None
    lua.execute("""
        ATTACK_CALLS = {}
        local orig_spawn = FAKE.byName.milan.spawnArmy
        FAKE.byName.milan.spawnArmy = function(...)
            local st = orig_spawn(...)
            st.attackArmy = function(self, target)
                ATTACK_CALLS[#ATTACK_CALLS + 1] = {
                    attacker = self.leader and self.leader.namedCharacter.fullName or "unknown",
                    target = target.leader and target.leader.namedCharacter.fullName or "unknown",
                }
                return 1
            end
            return st
        end
    """)
    res = lua.eval(f"BRIDGE.qa.force_ai_attack('milan', 112, 70, 'venice', '{target_id}')")
    assert res == "attack"
    calls = list(lua.eval("ATTACK_CALLS").values())
    assert len(calls) == 1
    assert calls[0]["target"] == target_id
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_ai_attack ok: attack" in log


def test_force_ai_attack_missing_target_army_reports_failure(lua):
    res = lua.eval("BRIDGE.qa.force_ai_attack('milan', 112, 70, 'venice', 'NonexistentGeneral')")
    assert res is None
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_ai_attack failed: " in log
    assert "unknown army 'NonexistentGeneral'" in log


def test_force_ai_siege_calls_siege_settlement_with_expected_args(lua):
    lua.execute("""
        SIEGE_CALLS = {}
        local orig_spawn = FAKE.byName.milan.spawnArmy
        FAKE.byName.milan.spawnArmy = function(...)
            local st = orig_spawn(...)
            st.siegeSettlement = function(self, s)
                SIEGE_CALLS[#SIEGE_CALLS + 1] = { settlement = s.name }
            end
            return st
        end
    """)
    res = lua.eval("BRIDGE.qa.force_ai_siege('milan', 112, 70, 'Venice')")
    assert res == "Venice"
    calls = list(lua.eval("SIEGE_CALLS").values())
    assert len(calls) == 1
    assert calls[0]["settlement"] == "Venice"
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_ai_siege ok: Venice" in log


def test_force_ai_siege_unknown_settlement_reports_failure(lua):
    res = lua.eval("BRIDGE.qa.force_ai_siege('milan', 112, 70, 'NonexistentCity')")
    assert res is None
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_ai_siege failed: " in log
    assert "unknown settlement 'NonexistentCity'" in log


def test_force_guild_offer_sets_standing_and_cooldown(lua):
    lua.execute("""
        GUILD_CALLS = {}
        COOLDOWN_CALLS = {}
        local s = FAKE.stratMap:getSettlement('Venice')
        s.setGuildStanding = function(self, guild_id, val)
            GUILD_CALLS[#GUILD_CALLS + 1] = { guild_id = guild_id, val = val }
        end
        M2TWEOP.setGuildCooldown = function(cd)
            COOLDOWN_CALLS[#COOLDOWN_CALLS + 1] = cd
        end
    """)
    res = lua.eval("BRIDGE.qa.force_guild_offer('Venice', 2)")
    assert res == "Venice"
    calls = list(lua.eval("GUILD_CALLS").values())
    assert len(calls) == 1
    assert calls[0]["guild_id"] == 2
    assert calls[0]["val"] == 300
    assert list(lua.eval("COOLDOWN_CALLS").values()) == []  # process-wide: it leaked past the bench 11-06
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_guild_offer ok: Venice" in log


def test_force_defect_switches_the_generals_faction(lua):
    gen = lua.eval("BRIDGE.qa.spawn_army('venice', 110, 70)")
    lua.execute("""
        SWITCHED = {}
        for _, st in ipairs(FAKE.byName.venice.stacks or {}) do
            if st.leader then
                st.leader.switchFaction = function(self, to, keep_army, keep_unit)
                    SWITCHED[#SWITCHED + 1] = to.name .. " " .. tostring(keep_army) .. " " .. tostring(keep_unit)
                end
            end
        end
    """)
    assert lua.eval(f"BRIDGE.qa.force_defect('venice', '{gen}', 'milan')") == gen
    assert list(lua.eval("SWITCHED").values()) == ["milan true true"]


def test_force_defect_unknown_army_reports_failure(lua):
    assert lua.eval("BRIDGE.qa.force_defect('venice', 'Nobody', 'milan')") is None
    assert "unknown army 'Nobody'" in (lua.root / "parley_bridge.log").read_text()


def test_force_attack_unknown_army_reports_failure(lua):
    assert lua.eval("BRIDGE.qa.force_attack('venice', 'Nobody', 'milan', 'Nobody2')") is None
    assert "qa: force_attack failed: " in (lua.root / "parley_bridge.log").read_text()


def test_forced_cases_and_helpers_write_no_process_wide_rule():
    # 11-06, twice: a forced case's rule change outlived the bench. campaignDb values and the guild cooldown
    # live in the game process, not the save, so the bench's reload doesn't undo them (maxAdoptionAge 80 and
    # guild cooldown 0 reached the live campaign).
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    banned = re.compile(r"getCampaignDb|setGuildCooldown")
    assert not banned.search((root / "games" / "qa" / "forced.toml").read_text())
    bridge = (root / "lua" / "parley_bridge.lua").read_text()
    helpers = re.findall(r"^        (force_\w+ = function.*?^        end,)", bridge, re.M | re.S)
    assert len(helpers) >= 8  # the scan found them: a guard that matches nothing passes
    for helper in helpers:
        code ="\n".join(line for line in helper.splitlines() if not line.strip().startswith("--"))
        assert not banned.search(code), helper.splitlines()[0]


def test_quiet_off_stops_the_quiet_step_until_the_next_load(lua):
    # rebellions and offers are what quiet holds off: a case can't test them with it on (11-06)
    assert lua.eval("BRIDGE.qa.quiet_off()") == "off"
    assert (lua.root / "quiet_off.txt").exists()
    assert lua.eval("BRIDGE.qa.quiet()") == "pope=quiet off"
    lua.execute(f"BRIDGE.setup('{lua.root}')")
    assert not (lua.root / "quiet_off.txt").exists()


def test_force_jihad_starts_it_on_the_town(lua):
    lua.execute("""
        CALLS = {}
        M2TW = { campaign = { jihad = { start = function(self, s, t, c) CALLS[#CALLS + 1] = s.name .. " " .. t end } } }
    """)
    assert lua.eval("BRIDGE.qa.force_jihad('Venice')") == "Venice"
    assert list(lua.eval("CALLS").values()) == ["Venice 10"]


GAME_OVER = "game over screen at 11:51:19: 2026-11-06 11:51:19 campaign over: end_campaign_scroll on screen"


def test_a_case_expecting_the_defeat_passes_when_the_game_goes_down_on_it():
    # bench 11-06: forced_campaign_lost reached the screen and failed, because trouble fires before the expect
    from parley.qa.cases import Case, Expect
    from parley.qa.runner import _down_was_expected

    case = Case(name="c", expect=[Expect(log="campaign over: end_campaign_scroll on screen")])
    assert _down_was_expected(case, GAME_OVER)


def test_a_case_not_expecting_the_defeat_still_fails_on_it():
    from parley.qa.cases import Case, Expect
    from parley.qa.runner import _down_was_expected

    assert not _down_was_expected(Case(name="c", expect=[Expect(log="something else")]), GAME_OVER)


def test_a_crash_never_counts_as_expected_whatever_the_regex():
    from parley.qa.cases import Case, Expect
    from parley.qa.runner import _down_was_expected

    crash = "game crashed at 11:51:19 (medieval2.exe not running): campaign over: end_campaign_scroll on screen"
    assert not _down_was_expected(Case(name="c", expect=[Expect(log="campaign over")]), crash)


def test_force_lose_towns_keeps_the_named_town(lua):
    lua.execute("""
        MOVED = {}
        local function town(name)
            return { name = name, changeOwner = function(self, to, conv) MOVED[#MOVED + 1] = self.name .. ">" .. to.name end }
        end
        local towns = { town('A'), town('Keep'), town('B') }
        local eng = FAKE.byName.england or FAKE.factions[1]
        eng.settlementsNum = 3
        eng.getSettlement = function(self, i) return towns[i + 1] end
        FAKE.campaign.getFaction = function(self, name)
            if name == 'england' then return eng end
            if name == 'slave' then return { name = 'slave' } end
        end
    """)
    assert lua.eval("BRIDGE.qa.force_lose_towns('england', 'Keep')") == 2
    assert sorted(lua.eval("MOVED").values()) == ["A>slave", "B>slave"]


def test_force_empty_town_kills_each_unit(lua):
    lua.execute("""
        KILLED = {}
        local function unit(n) return { kill = function(self, count) KILLED[#KILLED + 1] = n .. ":" .. count end } end
        local s = FAKE.stratMap:getSettlement('Venice')
        s.army = { numOfUnits = 2, getUnit = function(self, i) return unit(i) end }
    """)
    assert lua.eval("BRIDGE.qa.force_empty_town('Venice')") == 2
    assert list(lua.eval("KILLED").values()) == ["1:9999", "0:9999"]


def test_force_empty_town_unknown_settlement_reports_failure(lua):
    assert lua.eval("BRIDGE.qa.force_empty_town('Nowhere')") is None
    assert "unknown settlement 'Nowhere'" in (lua.root / "parley_bridge.log").read_text()


def test_no_forced_case_passes_on_its_own_setup_lines():
    # 11-06, twice: cases passed in 0.1 s because their regex matched the helper's "ok" line, its control
    # echo, or the bridge's routine "auto-resolve all battles on". The game's reaction has to be the proof.
    import re
    from pathlib import Path

    from parley.qa.cases import load_suite

    suite = load_suite(Path(__file__).resolve().parent.parent / "games" / "qa" / "forced.toml")
    for case in suite.cases:
        bound = {"rival": "denmark", "groom": "Nicholas", "garrison_town": "London", "at": "1,2", "offered": "X"}
        # what each setup call logs: "qa: <helper> ok: <what it returns>", echoed by the control line
        noise = ["2026-11-06 08:00:00 autoplay: auto-resolve all battles on\n"]
        for step in case.setup:
            call = re.search(r'M\.qa\.(\w+)\(([^)]*)\)', step.lua if hasattr(step, "lua") else str(step))
            if call:
                args = call.group(2).replace('"', "")
                noise.append(f"2026-11-06 08:00:00 qa: {call.group(1)} ok: {args}\n")
                noise.append(f"2026-11-06 08:00:00 control: lua -> {args}\n")
        log = "".join(noise)
        for exp in case.expect:
            if exp.log is None:
                continue
            pattern = exp.log
            for k, v in bound.items():
                pattern = pattern.replace(f"${k}", v)
            assert not re.search(pattern, log, re.MULTILINE), f"{case.name}: {exp.log} passes on setup lines alone"


def test_force_guild_offer_unknown_settlement_reports_failure(lua):
    res = lua.eval("BRIDGE.qa.force_guild_offer('NonexistentCity', 2)")
    assert res is None
    log = (lua.root / "parley_bridge.log").read_text()
    assert "qa: force_guild_offer failed: " in log
    assert "unknown settlement 'NonexistentCity'" in log


def test_scan_ui_logs_campaign_over_when_end_campaign_scroll_found(lua):
    # the scan reads what is on screen (gameSTDUI.getOpenUiElements), not a list of names
    log_file = lua.root / "parley_bridge.log"
    lua.execute("FAKE.open_scroll('prebattle_scroll', {})")
    lua.eval("BRIDGE.scan_ui('watcher')")
    log = log_file.read_text() if log_file.exists() else ""
    assert "campaign over: end_campaign_scroll on screen" not in log

    lua.execute("FAKE.open_scroll('end_campaign_scroll', {'ok_button'})")
    lua.eval("BRIDGE.scan_ui('watcher')")
    log = log_file.read_text()
    assert log.count("campaign over: end_campaign_scroll on screen") == 1

    # found by name but closed (cut loose from strat_ui): not over
    lua.execute("FAKE.closed = { end_campaign_scroll = true }")
    log_file.unlink(missing_ok=True)
    lua.eval("BRIDGE.scan_ui('watcher')")
    log = log_file.read_text() if log_file.exists() else ""
    assert "campaign over: end_campaign_scroll on screen" not in log


def test_a_human_turn_start_says_each_step_first(lua):
    # 11-06 12:29: a live crash stopped the log inside the turn start, and a replay went through
    autoplay(lua)
    start_turn(lua, "venice")
    text = (lua.root / "parley_bridge.log").read_text()
    steps = ["autoplay_turn_started", "set_governors", "follow", "apply_orders", "done"]
    at = [text.find(f"turn start venice: {s}") for s in steps]
    assert -1 not in at and at == sorted(at), dict(zip(steps, at))


def test_marrying_names_the_man_before_the_call(lua):
    lua.execute("""
        ORDER = {}
        ENG = { name = 'england', numOfNamedCharacters = 1, named = { { fullName = 'Loefwine', isMale = 1, isAlive = true, age = 55, isFamily = 1,
            marryWife = function(self) self.spouse = {} return {} end } } }
        ENG.getNamedCharacter = function(self, i) return self.named[i + 1] end
    """)
    lua.eval("BRIDGE.marry_singles(ENG)")
    assert "marrying Loefwine age 55" in (lua.root / "parley_bridge.log").read_text()


def test_a_man_whose_marriage_died_with_the_game_is_not_married_again(lua):
    # live 11-14 16:44:59 (scratch turn 506): "marrying Phillip Hasting age 16" was the bridge's last
    # line before the crash (00C4E8BD); a marriage still under way at a load means it took the game down
    lua.execute("""
        local function man(n) return { fullName = n, isMale = 1, isAlive = true, age = 16, isFamily = 1,
            marryWife = function(self) self.spouse = {} return {} end } end
        ENG = { name = 'england', numOfNamedCharacters = 2, named = { man('Phillip Hasting'), man('Harold Dobes') } }
        ENG.getNamedCharacter = function(self, i) return self.named[i + 1] end
    """)
    (lua.root / "marrying.txt").write_text("Phillip Hasting")
    wed = lua.eval("BRIDGE.marry_singles(ENG)")[0]
    assert list(wed.values()) == ["Harold Dobes"]
    log = (lua.root / "parley_bridge.log").read_text()
    assert "Phillip Hasting was being married when the game died; he is not married again" in log
    assert (lua.root / "marry_skip.txt").read_text().splitlines() == ["Phillip Hasting"]
    assert (lua.root / "marrying.txt").read_text() == ""  # Harold's marriage returned
    # the skip list holds at the next turn start, with no marker
    lua.execute("ENG.named[1].spouse = nil")
    assert list(lua.eval("BRIDGE.marry_singles(ENG)")[0].values()) == []
