import json
import threading
import time

from parley.bridge import TurnDir
from parley.config import GameConfig, SeatConfig, load_config
from parley.orchestrator import Orchestrator
from parley.protocol import Orders, SendGold, SetStance
from parley.seats import FakeSeat, SeatError


def _config(tmp_path, factions=("venice",)):
    (tmp_path / "saves").mkdir(exist_ok=True)
    (tmp_path / "mods" / "parley" / "saves").mkdir(parents=True, exist_ok=True)
    return GameConfig(
        game_id="test", turn_root=tmp_path / "turns", save_dir=tmp_path / "saves",
        backup_dir=tmp_path / "backups",
        seats={f: SeatConfig(brain="fake", persona=f"You rule {f}.") for f in factions},
    )


def _pending(cfg, faction, venice_state_dict, turn=1):
    d = TurnDir(cfg.turn_root).path_for(cfg.game_id, turn, faction)
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({**venice_state_dict, "faction": faction}))
    return d


def _orders(*items):
    return Orders(protocol=1, game_id="x", turn=0, faction="x", orders=list(items))


def test_popup_decisions_go_to_the_decider_brain_when_set(tmp_path):
    # live: a cheap seat declined a 4-star general; family offers and votes can use a stronger brain
    cfg = _config(tmp_path, ("venice", "milan"))
    from parley.config import AutoplayConfig
    cfg.autoplay = AutoplayConfig()
    cfg.seats["venice"].brain = "agy:cheap"  # the seats are handed in; only the names differ
    cfg.seats["venice"].decider = "fake"
    seats = {"venice": FakeSeat(), "milan": FakeSeat()}
    orch = Orchestrator(cfg, seats)
    assert orch.popups.seats["venice"] is not seats["venice"]
    assert orch.popups.seats["milan"] is seats["milan"]


def test_orchestrator_passes_ladder_and_decision_log_to_popups(tmp_path):
    cfg = _config(tmp_path, ("venice", "milan"))
    from parley.config import AutoplayConfig
    cfg.autoplay = AutoplayConfig()
    cfg.seats["venice"].ladder = True
    seats = {"venice": FakeSeat(), "milan": FakeSeat()}
    orch = Orchestrator(cfg, seats)
    assert orch.popups.ladder == {"venice"}
    assert orch.popups.decision_log is orch.decision_log


def test_orchestrator_wires_reader_to_popups(tmp_path):
    from parley.config import AutoplayConfig
    from parley.popups import read_agy
    cfg = _config(tmp_path, ("venice",))
    cfg.autoplay = AutoplayConfig()
    cfg.reader = "agy:gemini-3.8-flash-low"
    orch = Orchestrator(cfg, {"venice": FakeSeat()})
    assert orch.popups.read.func is read_agy
    assert orch.popups.read.keywords == {"model": "gemini-3.8-flash-low"}


def test_a_failing_decider_falls_back_to_the_seats_own_brain():
    # live: the Opus decider hit a session limit; the decisions were declined unanswered
    import pytest
    from parley.orchestrator import Fallback
    from parley.seats.base import SeatLimit

    class Seat:
        def __init__(self, answer):
            self.answer = answer

        def chat(self, prompt, *, timeout):
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

    limited = Seat(SeatLimit("claude usage limit: You've hit your session limit"))
    assert Fallback(limited, Seat("ACCEPT. Own brain."), "england").chat("p", timeout=1) == "ACCEPT. Own brain."
    assert Fallback(Seat("DECLINE"), Seat("ACCEPT"), "england").chat("p", timeout=1) == "DECLINE"
    with pytest.raises(SeatLimit):  # both at their limit: the game pauses as before
        Fallback(limited, limited, "england").chat("p", timeout=1)


def test_a_failing_turn_brain_falls_back_with_warning_and_split_timeouts(
    tmp_path, venice_state_dict, monkeypatch, caplog
):
    # live: France's Gemini seat hung 4 of 11 turns until the 240 s timeout
    import logging
    cfg = _config(tmp_path, ("france",))
    cfg.seat_timeout = 240
    cfg.fallback_reserve = 90
    cfg.seats["france"].brain = "agy:gemini-4-argon-medium"
    cfg.seats["france"].fallback = "claude:sonnet"
    primary = FakeSeat([SeatError("agy timed out after 240.0s"), _orders(SetStance(to="milan", stance="peace"))],
                       name="agy:gemini-4-argon-medium")
    backup = FakeSeat([_orders(SetStance(to="milan", stance="war"))], name="claude:sonnet")
    monkeypatch.setattr("parley.orchestrator.make_seat",
                        lambda spec, budget=None: backup if spec == "claude:sonnet" else FakeSeat())
    orch = Orchestrator(cfg, {"france": primary})

    d1 = _pending(cfg, "france", {**venice_state_dict, "turn": 177}, turn=177)
    with caplog.at_level(logging.WARNING, logger="parley"):
        orch.run_once()
    orders1 = Orders.model_validate_json((d1 / "orders.json").read_text())
    assert [(o.type, o.stance) for o in orders1.orders] == [("set_stance", "war")]
    assert ("france turn 177: agy:gemini-4-argon-medium failed (agy timed out after 240.0s); "
            "asked claude:sonnet instead") in caplog.text
    assert primary.timeouts == [150] and backup.timeouts == [90]

    # when the primary succeeds, the fallback is not used and the primary's timeout floors at 60 s
    cfg.seat_timeout = 120
    caplog.clear()
    d2 = _pending(cfg, "france", {**venice_state_dict, "turn": 178}, turn=178)
    with caplog.at_level(logging.WARNING, logger="parley"):
        orch.run_once()
    orders2 = Orders.model_validate_json((d2 / "orders.json").read_text())
    assert [(o.type, o.stance) for o in orders2.orders] == [("set_stance", "peace")]
    assert caplog.text == ""
    assert primary.timeouts == [150, 60] and backup.timeouts == [90]


def test_the_session_limit_wording_counts_as_a_usage_limit():
    from parley.seats.claude_code import LIMIT
    assert LIMIT.search("You've hit your session limit · resets 4pm (America/Indiana/Indianapolis)")
    assert LIMIT.search("You've hit your limit") and LIMIT.search("Claude AI usage limit reached")
    assert not LIMIT.search("claude exit 1: model not found")


def test_settlements_seen_on_earlier_turns_are_remembered(tmp_path, venice_state_dict):
    # the adviser, live: "have you fully explored Ireland and England?"
    from parley.protocol import StateReport
    cfg = _config(tmp_path)
    cork = {"id": "Cork", "name": "Cork", "faction": "slave", "x": 80, "y": 160,
            "garrison_strength": 400, "garrison_men": 75, "garrison_units": 2}
    d = _pending(cfg, "venice", {**venice_state_dict, "turn": 3, "nearby_settlements": [cork]}, turn=3)
    (d / "orders.json").write_text("{}")
    now = StateReport.model_validate({**venice_state_dict, "turn": 5, "nearby_settlements": []})
    orch = Orchestrator(cfg, {"venice": FakeSeat()})
    [seen] = orch._remembered(now)
    assert (seen.id, seen.seen_turn, seen.garrison_strength, seen.garrison_men, seen.garrison_units) == (
        "Cork", 3, 400, 75, 2)
    in_sight = now.model_copy(update={"nearby_settlements": [StateReport.model_validate(
        {**venice_state_dict, "nearby_settlements": [cork]}).nearby_settlements[0]]})
    assert orch._remembered(in_sight) == []  # in sight now: listed there, not here


def test_answers_each_pending_once(tmp_path, venice_state_dict):
    cfg = _config(tmp_path, ("venice", "milan"))
    for f in ("venice", "milan"):
        _pending(cfg, f, venice_state_dict)
    orch = Orchestrator(cfg, {f: FakeSeat() for f in ("venice", "milan")})
    assert orch.run_once() == 2
    assert orch.run_once() == 0


def test_restart_mid_turn_no_double_answer(tmp_path, venice_state_dict):
    cfg = _config(tmp_path, ("venice", "milan"))
    done = _pending(cfg, "venice", venice_state_dict)
    (done / "orders.json").write_text("{}")
    _pending(cfg, "milan", venice_state_dict)
    assert Orchestrator(cfg, {"venice": FakeSeat(), "milan": FakeSeat()}).run_once() == 1
    assert (done / "orders.json").read_text() == "{}"


def test_seat_error_still_ends_turn(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    d = _pending(cfg, "venice", venice_state_dict)
    Orchestrator(cfg, {"venice": FakeSeat([SeatError("down")])}).run_once()
    orders = Orders.model_validate_json((d / "orders.json").read_text())
    assert orders.orders == [] and "down" in orders.note


def test_a_usage_limit_pauses_the_game_and_keeps_the_turn_open(tmp_path, venice_state_dict):
    # live: every Claude seat failed for an hour; autoplay ended turns with silent rulers
    from parley.seats.base import SeatLimit
    cfg = _config(tmp_path)
    d = _pending(cfg, "venice", venice_state_dict)
    orch = Orchestrator(cfg, {"venice": FakeSeat([SeatLimit("claude usage limit: reached")])})
    assert orch.run_once() == 0
    assert not (d / "orders.json").exists()
    assert "usage limit" in (cfg.turn_root / "paused.txt").read_text()
    assert orch.run_once() == 0  # waits out the retry period
    orch._retry_at = 0
    assert orch.run_once() == 1  # the seat answers again
    assert (d / "orders.json").exists() and not (cfg.turn_root / "paused.txt").exists()


def test_army_order_results_say_how_the_armies_stand_now(venice_report):
    from parley.orchestrator import _armies_now
    from parley.protocol import Army, MergeArmies
    paul = Army(id="Paul", leader="Paul", x=100, y=130, strength=200, units=1)
    caen = Army(id="garrison:Caen", x=104, y=134, strength=3000, units=15, in_settlement="Caen")
    r = venice_report.model_copy(update={"armies": [paul, caen]})
    merge = MergeArmies(army="garrison:Caen", into="Paul")
    assert _armies_now(merge, r, {"Paul", "garrison:Caen"}) == (
        "garrison:Caen has 15 units, in Caen; Paul has 1 units, at (100,130)")
    gone = r.model_copy(update={"armies": [paul.model_copy(update={"units": 16})]})
    assert "garrison:Caen is no longer one of your armies" in _armies_now(merge, gone, {"Paul", "garrison:Caen"})


def test_attack_result_shows_the_target_as_it_stands(venice_report):
    # live: "attack: done" with no battle; Henry had been three tiles off with 2 moves left
    from parley.orchestrator import _armies_now
    from parley.protocol import Army, Attack
    henry = Army(id="Henry", leader="Henry", x=102, y=168, strength=8153, units=16)
    canmore = Army(id="Canmore", leader="Canmore", faction="scotland", x=101, y=169, strength=5784,
                   units=18, distance=1)
    r = venice_report.model_copy(update={"armies": [henry], "visible_enemies": [canmore]})
    text = _armies_now(Attack(army="Henry", target="Canmore"), r, {"Henry"})
    assert "Henry has 16 units, at (102,168)" in text
    assert "Canmore has 18 units, at (101,169), 1 tiles from you" in text


def test_a_plan_with_no_orders_is_asked_again(tmp_path, venice_state_dict):
    # live: Opus wrote ten orders into its note and returned an empty orders list
    cfg = _config(tmp_path)
    d = _pending(cfg, "venice", venice_state_dict)
    plan = "Recruit knights in York, merge the garrison into Henry, attack Geoffrey. " * 6
    empty = Orders(protocol=1, game_id="test", turn=3, faction="venice", orders=[], note=plan)
    full = Orders(protocol=1, game_id="test", turn=3, faction="venice",
                  orders=[SetStance(to="milan", stance="war")], note=plan)
    seat = FakeSeat([empty, full])
    Orchestrator(cfg, {"venice": seat}).run_once()
    orders = Orders.model_validate_json((d / "orders.json").read_text())
    assert [o.type for o in orders.orders] == ["set_stance"]


def test_invalid_orders_filtered_and_recorded(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    d = _pending(cfg, "venice", venice_state_dict)
    seat = FakeSeat([_orders(SendGold(to="milan", amount=99999), SetStance(to="milan", stance="alliance"))])
    Orchestrator(cfg, {"venice": seat}).run_once()
    assert len(Orders.model_validate_json((d / "orders.json").read_text()).orders) == 1
    rejected = json.loads((d / "rejected.json").read_text())
    assert len(rejected) == 1 and "treasury" in rejected[0]["reason"]


def test_artifacts_written(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    d = _pending(cfg, "venice", venice_state_dict)
    Orchestrator(cfg, {"venice": FakeSeat()}).run_once()
    assert "You rule venice." in (d / "prompt.txt").read_text()
    assert (d / "answer.txt").exists()


def test_unconfigured_faction_skipped(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    d = _pending(cfg, "england", venice_state_dict)
    assert Orchestrator(cfg, {"venice": FakeSeat()}).run_once() == 0
    assert not (d / "orders.json").exists()


def test_bad_state_file_left_for_retry(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    d = _pending(cfg, "venice", venice_state_dict)
    (d / "state.json").write_text('{"protocol": 1, "game_')
    assert Orchestrator(cfg, {"venice": FakeSeat()}).run_once() == 0
    assert not (d / "orders.json").exists()


def test_save_backed_up_before_turn(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    (cfg.save_dir / "eng.sav").write_text("old-manual-save")
    (cfg.mod_save_dir / "Autosave-1.sav").write_text("mod-autosave")
    _pending(cfg, "venice", venice_state_dict)
    Orchestrator(cfg, {"venice": FakeSeat()}).run_once()
    assert [p.name for p in cfg.backup_dir.iterdir()] == ["turn-0001-venice-Autosave-1.sav"]
    assert (cfg.backup_dir / "turn-0001-venice-Autosave-1.sav").read_text() == "mod-autosave"


def test_parallel_seats(tmp_path, venice_state_dict):
    # both seats must be inside decide() at once: a barrier only two concurrent callers pass. Was a
    # wall-clock bound (< 1.8 s for two 1 s seats), which failed on slow hardware (11-04).
    import threading

    barrier = threading.Barrier(2, timeout=10)
    met = []

    class Meeting(FakeSeat):
        def decide(self, prompt, **kw):
            barrier.wait()  # raises BrokenBarrierError if the other seat never arrives (sequential)
            met.append(kw["faction"])
            return super().decide(prompt, **kw)

    cfg = _config(tmp_path, ("venice", "milan"))
    for f in ("venice", "milan"):
        _pending(cfg, f, venice_state_dict)
    Orchestrator(cfg, {f: Meeting() for f in ("venice", "milan")}).run_once()
    assert sorted(met) == ["milan", "venice"]


def test_load_config(tmp_path):
    p = tmp_path / "g.toml"
    p.write_text(
        'game_id = "g1"\nturn_root = "runs/turns"\nsave_dir = "saves"\n'
        '[seats.venice]\nbrain = "claude:sonnet"\npersona = "Doge."\n'
    )
    cfg = load_config(p)
    assert cfg.seats["venice"].brain == "claude:sonnet" and cfg.seats["venice"].fallback == ""
    assert cfg.turn_root == tmp_path / "runs" / "turns"
    assert cfg.seat_timeout == 120 and cfg.fallback_reserve == 90 and cfg.keep_backups == 20

    p2 = tmp_path / "g2.toml"
    p2.write_text(
        'game_id = "g2"\nturn_root = "runs/turns"\nsave_dir = "saves"\n'
        'seat_timeout = 240\nfallback_reserve = 75\n'
        '[seats.france]\nbrain = "agy:gemini-4-argon-medium"\nfallback = "claude:sonnet"\npersona = "King."\n'
    )
    cfg2 = load_config(p2)
    assert cfg2.seat_timeout == 240 and cfg2.fallback_reserve == 75
    assert cfg2.seats["france"].fallback == "claude:sonnet"


# --- final review fixes ---

def test_unexpected_seat_exception_ends_turn(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    d = _pending(cfg, "venice", venice_state_dict)
    Orchestrator(cfg, {"venice": FakeSeat([RuntimeError("boom")])}).run_once()
    orders = Orders.model_validate_json((d / "orders.json").read_text())
    assert orders.orders == [] and "boom" in orders.note


def test_report_not_matching_its_dir_is_refused(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    d = _pending(cfg, "venice", venice_state_dict)
    (d / "state.json").write_text(json.dumps({**venice_state_dict, "faction": "Venice"}))
    Orchestrator(cfg, {"venice": FakeSeat()}).run_once()
    orders = Orders.model_validate_json((d / "orders.json").read_text())
    assert orders.orders == [] and "mismatch" in orders.note and orders.faction == "venice"


def test_one_backup_per_poll(tmp_path, venice_state_dict):
    cfg = _config(tmp_path, ("venice", "milan"))
    (cfg.mod_save_dir / "campaign.sav").write_text("save")
    for f in ("venice", "milan"):
        _pending(cfg, f, venice_state_dict)
    Orchestrator(cfg, {f: FakeSeat() for f in ("venice", "milan")}).run_once()
    assert len(list(cfg.backup_dir.iterdir())) == 1


def test_run_forever_survives_errors(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    orch = Orchestrator(cfg, {"venice": FakeSeat()})
    calls = []

    def flaky(wait=True):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk full")
        raise KeyboardInterrupt
    monkeypatch.setattr(orch, "run_once", flaky)
    try:
        orch.run_forever(poll=0)
    except KeyboardInterrupt:
        pass
    assert len(calls) == 2


def test_pending_ignores_other_games(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    other = TurnDir(cfg.turn_root).path_for("OTHERGAME", 1, "venice")
    other.mkdir(parents=True)
    (other / "state.json").write_text(json.dumps(venice_state_dict))
    assert Orchestrator(cfg, {"venice": FakeSeat()}).run_once() == 0


def test_reloaded_save_reanswers_turn(tmp_path, venice_state_dict):
    import os
    cfg = _config(tmp_path)
    d = _pending(cfg, "venice", venice_state_dict)
    orch = Orchestrator(cfg, {"venice": FakeSeat()})
    assert orch.run_once() == 1
    os.utime(d / "orders.json", (1000, 1000))  # the game rewrote state.json after a reload
    assert orch.run_once() == 1
    assert list(d.glob("superseded-*/orders.json"))


def test_rejections_reach_next_prompt(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    _pending(cfg, "venice", venice_state_dict, turn=1)
    seat = FakeSeat([_orders(SendGold(to="milan", amount=99999), SetStance(to="milan", stance="alliance"))])
    orch = Orchestrator(cfg, {"venice": seat})
    orch.run_once()
    # the game applied the one kept order, which it numbers 0
    state2 = {**venice_state_dict, "turn": 2,
              "last_results": [{"index": 0, "type": "set_stance", "ok": True}]}
    d2 = TurnDir(cfg.turn_root).path_for(cfg.game_id, 2, "venice")
    d2.mkdir(parents=True, exist_ok=True)
    (d2 / "state.json").write_text(json.dumps(state2))
    orch.run_once()
    prompt = (d2 / "prompt.txt").read_text()
    assert "YOUR ORDERS REFUSED LAST TURN" in prompt and "- send_gold" in prompt
    assert "order 1 (set_stance): done" in prompt


def test_bridge_config_published(tmp_path):
    cfg = _config(tmp_path, ("venice", "milan"))
    Orchestrator(cfg, {}).publish_bridge_config()
    lines = (cfg.turn_root / "bridge.txt").read_text().splitlines()
    assert lines == ["game_id=test", "faction=milan", "faction=venice"]


def test_malformed_orders_reported_in_the_rulers_own_numbering(tmp_path, venice_state_dict):
    from parley.seats.base import to_orders

    class Sloppy(FakeSeat):
        def decide(self, prompt, *, game_id, turn, faction, timeout):
            return to_orders({"orders": [
                {"type": "march_on", "army": "X"},                         # 0: malformed
                {"type": "send_gold", "to": "milan", "amount": 999999},   # 1: valid, too costly
                {"type": "set_stance", "to": "milan", "stance": "peace"},  # 2: kept
            ]}, game_id=game_id, turn=turn, faction=faction), "{}"

    cfg = _config(tmp_path, ("venice", "milan"))
    d = _pending(cfg, "venice", venice_state_dict)
    Orchestrator(cfg, {"venice": Sloppy()}).run_once()
    rejected = {r["index"]: r for r in json.loads((d / "rejected.json").read_text())}
    assert "target_settlement" in rejected[0]["reason"] and "treasury" in rejected[1]["reason"]
    assert json.loads((d / "index_map.json").read_text()) == [2]


def test_seat_control_reaches_prompt_checker_and_bridge(tmp_path, venice_state_dict):
    from parley.protocol import MarchOn
    cfg = _config(tmp_path, ("venice", "milan"))
    cfg.seats["venice"] = cfg.seats["venice"].model_copy(update={"control": "diplomat"})
    d = _pending(cfg, "venice", venice_state_dict)
    seat = FakeSeat([_orders(SetStance(to="milan", stance="peace"),
                             MarchOn(army="Doge Enrico", target_settlement="Milan"))])
    orch = Orchestrator(cfg, {"venice": seat})
    orch.run_once()
    assert "You command: diplomacy." in (d / "prompt.txt").read_text()
    assert [o["type"] for o in json.loads((d / "orders.json").read_text())["orders"]] == ["set_stance"]
    assert "not yours to command" in (d / "rejected.json").read_text()
    orch.publish_bridge_config()
    lines = (cfg.turn_root / "bridge.txt").read_text().splitlines()
    assert "control=venice:diplomacy" in lines and not any(l.startswith("control=milan") for l in lines)


def test_bridge_config_carries_autoplay(tmp_path):
    from parley.config import AutoplayConfig
    cfg = _config(tmp_path, ("venice",)).model_copy(update={"autoplay": AutoplayConfig(wait=90, until_turn=30)})
    Orchestrator(cfg, {}).publish_bridge_config()
    lines = (cfg.turn_root / "bridge.txt").read_text().splitlines()
    assert lines[-4:] == ["autoplay=1", "autoplay_wait=90", "autoplay_until=30", "papal_hands_off=1"]


def test_bridge_config_can_switch_off_the_end_turn_hold_for_offers(tmp_path):
    from parley.config import AutoplayConfig
    cfg = _config(tmp_path, ("venice",)).model_copy(update={"autoplay": AutoplayConfig(hold_decisions=False)})
    Orchestrator(cfg, {}).publish_bridge_config()
    assert "autoplay_hold_decisions=0" in (cfg.turn_root / "bridge.txt").read_text().splitlines()


def test_bridge_config_carries_playtest_funds(tmp_path):
    cfg = _config(tmp_path, ("venice", "milan"))
    cfg.seats["venice"] = cfg.seats["venice"].model_copy(update={"playtest_funds": True})
    Orchestrator(cfg, {}).publish_bridge_config()
    lines = (cfg.turn_root / "bridge.txt").read_text().splitlines()
    assert "playtest_funds=venice:50000" in lines
    assert not any(l.startswith("playtest_funds=milan") for l in lines)

    # custom amount
    cfg.seats["venice"] = cfg.seats["venice"].model_copy(update={"playtest_funds": True, "playtest_funds_amount": 75000})
    Orchestrator(cfg, {}).publish_bridge_config()
    lines = (cfg.turn_root / "bridge.txt").read_text().splitlines()
    assert "playtest_funds=venice:75000" in lines

    # switch off ignores amount
    cfg.seats["venice"] = cfg.seats["venice"].model_copy(update={"playtest_funds": False, "playtest_funds_amount": 75000})
    Orchestrator(cfg, {}).publish_bridge_config()
    lines = (cfg.turn_root / "bridge.txt").read_text().splitlines()
    assert not any(l.startswith("playtest_funds=venice") for l in lines)


def test_turn_dirs_prepared_ahead(tmp_path, venice_state_dict):
    cfg = _config(tmp_path, ("venice", "milan"))
    orch = Orchestrator(cfg, {f: FakeSeat() for f in ("venice", "milan")})
    orch.prepare_turn_dirs()  # nothing played yet: turns 0..LOOKAHEAD exist
    td = TurnDir(cfg.turn_root)
    assert td.path_for("test", 0, "milan").is_dir()  # the game's first turn is 0
    assert td.path_for("test", 1, "milan").is_dir()
    from parley.orchestrator import LOOKAHEAD
    late = 2 * LOOKAHEAD + 1  # well past the prepared range
    d = _pending(cfg, "venice", {**venice_state_dict, "turn": late}, turn=late)
    assert d.is_dir()
    orch.run_once()  # answering a turn prepares dirs up to that turn + LOOKAHEAD
    assert td.path_for("test", late + LOOKAHEAD, "venice").is_dir()
    assert td.path_for("test", late + LOOKAHEAD, "milan").is_dir()


def test_heartbeat_prepares_folders(tmp_path):
    cfg = _config(tmp_path, ("venice",))
    cfg.turn_root.mkdir(parents=True)
    (cfg.turn_root / "heartbeat.txt").write_text("turn=30\n")
    Orchestrator(cfg, {"venice": FakeSeat()}).run_once()
    from parley.orchestrator import LOOKAHEAD
    assert TurnDir(cfg.turn_root).path_for("test", 30 + LOOKAHEAD, "venice").is_dir()


def test_late_orders_reported_to_llm(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    seat = FakeSeat([_orders(SetStance(to="milan", stance="alliance"))])
    orch = Orchestrator(cfg, {"venice": seat})
    d1 = _pending(cfg, "venice", venice_state_dict, turn=1)
    (d1 / "late.txt").write_text("")  # the game started turn 2 before these orders existed
    orch.run_once()
    d2 = _pending(cfg, "venice", {**venice_state_dict, "turn": 2}, turn=2)
    orch.run_once()
    prompt = (d2 / "prompt.txt").read_text()
    assert "YOUR ORDERS REFUSED LAST TURN" in prompt and "- set_stance: arrived too late" in prompt


def test_undecodable_state_is_answered_not_retried_forever(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    d = _pending(cfg, "venice", venice_state_dict)
    raw = json.dumps({**venice_state_dict, "faction": "venice"}).encode()
    (d / "state.json").write_bytes(raw.replace(b"Doge Enrico", b"Ladis\xb3aw"))  # a cp1252 byte
    assert Orchestrator(cfg, {"venice": FakeSeat()}).run_once() == 1


def _say_orders(*says, note=""):
    from parley.protocol import Say
    return Orders(protocol=1, game_id="x", turn=0, faction="x", orders=[],
                  messages=[Say(to=t, text=x) for t, x in says], note=note)


def test_messages_queued_to_right_channel(tmp_path, venice_state_dict):
    from parley.store import Store
    cfg = _config(tmp_path, ("venice", "milan"))  # milan must be a player to receive messages
    _pending(cfg, "venice", venice_state_dict)
    seat = FakeSeat([_say_orders(("lobby", "Hear me"), ("milan", "Psst"))])
    Orchestrator(cfg, {"venice": seat}).run_once()
    out = [m for m in Store(cfg.turn_root / "test.db").unposted("test") if m.channel != "chronicle"]
    assert [(m.channel, m.text) for m in out] == [("lobby", "Hear me"), ("pair:milan|venice", "Psst")]


def test_note_never_queued(tmp_path, venice_state_dict):
    from parley.store import Store
    cfg = _config(tmp_path)
    _pending(cfg, "venice", venice_state_dict)
    seat = FakeSeat([_say_orders(("lobby", "Friends!"), note="I will betray them all")])
    Orchestrator(cfg, {"venice": seat}).run_once()
    texts = [m.text for m in Store(cfg.turn_root / "test.db").unposted("test") if m.channel != "chronicle"]
    assert texts == ["Friends!"]


def test_message_cap_across_turn(tmp_path, venice_state_dict):
    from parley.store import Store
    cfg = _config(tmp_path, ("venice", "milan"))
    d = _pending(cfg, "venice", venice_state_dict)
    seat = FakeSeat([_say_orders(*[("milan", f"m{i}") for i in range(4)])])
    Orchestrator(cfg, {"venice": seat}).run_once()
    assert len([m for m in Store(cfg.turn_root / "test.db").unposted("test") if m.channel != "chronicle"]) == 3
    rejected = json.loads((d / "messages.json").read_text())["rejected"]
    assert len(rejected) == 1 and "limit" in rejected[0]["reason"]


def test_diplomacy_reaches_prompt(tmp_path, venice_state_dict):
    from parley.store import Store
    cfg = _config(tmp_path)
    cfg.turn_root.mkdir(parents=True, exist_ok=True)
    Store(cfg.turn_root / "test.db").record("test", 1, "lobby", "human:england", "Venice, ally with me")
    d = _pending(cfg, "venice", venice_state_dict)
    Orchestrator(cfg, {"venice": FakeSeat()}).run_once()
    assert "Venice, ally with me" in (d / "prompt.txt").read_text()


def test_config_humans_discord_and_names(tmp_path):
    p = tmp_path / "g.toml"
    p.write_text(
        'game_id = "g1"\nturn_root = "t"\nsave_dir = "s"\n'
        '[humans]\nengland = "player_one"\n'
        '[discord]\nguild = "My Parley Server"\n'
        '[seats.venice]\nbrain = "fake"\npersona = "Doge."\nname = "Doge Enrico"\n'
    )
    cfg = load_config(p)
    assert cfg.humans == {"england": "player_one"}
    assert cfg.discord.guild == "My Parley Server" and cfg.discord.lobby == "lobby"
    assert cfg.seats["venice"].name == "Doge Enrico"


def test_chronicle_notice_when_all_rulers_decided(tmp_path, venice_state_dict):
    from parley.store import Store
    cfg = _config(tmp_path, ("venice", "milan"))
    orch = Orchestrator(cfg, {f: FakeSeat() for f in ("venice", "milan")})
    turn2 = {**venice_state_dict, "turn": 2}
    _pending(cfg, "venice", turn2, turn=2)
    orch.run_once()
    store = Store(cfg.turn_root / "test.db")
    assert [m for m in store.unposted("test") if m.channel == "chronicle"] == []  # milan not yet
    _pending(cfg, "milan", turn2, turn=2)
    orch.run_once()
    notices = [m for m in store.unposted("test") if m.channel == "chronicle"]
    assert len(notices) == 1 and "Turn 2" in notices[0].text and "end your turn" in notices[0].text
    orch.run_once()
    assert len([m for m in store.unposted("test") if m.channel == "chronicle"]) == 1  # once only


def test_notes_and_events_reach_next_prompt(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    seat = FakeSeat([Orders(protocol=1, game_id="x", turn=0, faction="x", orders=[],
                            note="Grudge: Milan insulted us.")])
    orch = Orchestrator(cfg, {"venice": seat})
    _pending(cfg, "venice", venice_state_dict, turn=1)
    orch.run_once()
    turn2 = {**venice_state_dict, "turn": 2, "treasury": 7000,
             "settlements": venice_state_dict["settlements"][:1]}
    d2 = _pending(cfg, "venice", turn2, turn=2)
    orch.run_once()
    prompt = (d2 / "prompt.txt").read_text()
    assert "[turn 1] Grudge: Milan insulted us." in prompt
    assert "You lost Ragusa." in prompt and "Treasury: 5000 → 7000 (+2000)." in prompt


def test_config_paths_expand_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = tmp_path / "g.toml"
    p.write_text('game_id = "g"\nturn_root = "~/game/parley_turns"\nsave_dir = "~/game/saves"\n'
                 '[seats.venice]\nbrain = "fake"\npersona = "p"\n')
    cfg = load_config(p)
    assert cfg.turn_root == tmp_path / "game" / "parley_turns"


def test_game_channel_defaults_to_game_id(tmp_path):
    p = tmp_path / "g.toml"
    p.write_text('game_id = "First Game"\nturn_root = "t"\nsave_dir = "s"\n'
                 '[discord]\nguild = "G"\n[seats.venice]\nbrain = "fake"\npersona = "p"\n')
    assert load_config(p).discord.game_channel == "first-game"


def test_transfers_to_humans_announced_once(tmp_path, venice_state_dict):
    from parley.config import GameConfig, SeatConfig
    from parley.store import Store
    cfg = _config(tmp_path, ("venice",))
    cfg.humans = {"england": "player_one"}
    d = _pending(cfg, "venice", venice_state_dict, turn=1)
    seat = FakeSeat([_orders(SendGold(to="england", amount=500), SetStance(to="milan", stance="peace"))])
    venice_state_dict["factions"].append({"id": "england", "name": "England", "stance": "peace"})
    (d / "state.json").write_text(json.dumps({**venice_state_dict, "faction": "venice"}))
    orch = Orchestrator(cfg, {"venice": seat})
    orch.run_once()
    (d / "results.json").write_text(json.dumps([
        {"index": 0, "type": "send_gold", "ok": True, "reason": ""},
        {"index": 1, "type": "set_stance", "ok": True, "reason": ""}]))  # the game applied them
    orch.run_once()
    orch.run_once()
    out = Store(cfg.turn_root / "test.db").unposted("test")
    notices = [(m.channel, m.text) for m in out if "sent" in m.text]
    # private between the two sides, never in the public game channel
    assert notices == [("pair:england|venice", "📜 Venice sent England 500 florins.")]


def test_second_orchestrator_refused(tmp_path):
    import pytest
    cfg = _config(tmp_path)
    first = Orchestrator(cfg, {})
    first.acquire()
    with pytest.raises(RuntimeError, match="already running"):
        Orchestrator(cfg, {}).acquire()
    first.release()


def test_the_standing_plan_carries_to_the_next_turn(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    d = _pending(cfg, "venice", {**venice_state_dict, "turn": 3}, turn=3)
    orch = Orchestrator(cfg, {"venice": FakeSeat([_orders()])})
    for turn, plan in ((1, "Old plan"), (2, "Take Milan by turn 12")):
        past = orch.turns.path_for("test", turn, "venice")
        past.mkdir(parents=True, exist_ok=True)
        (past / "orders.json").write_text(Orders(protocol=1, game_id="test", turn=turn, faction="venice",
                                                 orders=[], plan=plan).model_dump_json())
    orch.run_once()
    prompt = (d / "prompt.txt").read_text()
    assert "Take Milan by turn 12" in prompt and "Old plan" not in prompt


def test_a_review_keeps_lessons_that_later_prompts_recall(tmp_path, venice_state_dict):
    from parley import lessons
    from parley.orchestrator import REVIEW_EVERY
    cfg = _config(tmp_path)
    answer = '```json\n{"lessons": [{"text": "Field an army before sieges start.", "evidence": "turn 19"}]}\n```'
    seat = FakeSeat([_orders()], chats=[answer])
    orch = Orchestrator(cfg, {"venice": seat})
    for turn in (REVIEW_EVERY - 1, REVIEW_EVERY):
        past = orch.turns.path_for("test", turn, "venice")
        past.mkdir(parents=True, exist_ok=True)
        (past / "orders.json").write_text(Orders(protocol=1, game_id="test", turn=turn, faction="venice",
                                                 orders=[], note=f"note {turn}").model_dump_json())
    added = orch.review("venice", REVIEW_EVERY)
    assert [x.text for x in added] == ["Field an army before sieges start."]
    d = _pending(cfg, "venice", {**venice_state_dict, "turn": REVIEW_EVERY + 1}, turn=REVIEW_EVERY + 1)
    orch.run_once()
    prompt = (d / "prompt.txt").read_text()
    assert "LESSONS FROM YOUR PAST GAMES" in prompt and "- Field an army before sieges start." in prompt
    lessons.veto(orch.lessons_root, added[0].id)
    assert orch._lessons("venice") == []


def test_seat_bench_replays_a_turn(tmp_path, venice_state_dict, monkeypatch):
    from parley import bench
    from parley.seats import SeatError
    (tmp_path / "prompt.txt").write_text("the prompt")
    (tmp_path / "state.json").write_text(json.dumps(venice_state_dict))
    seats = {"good": FakeSeat([_orders(SetStance(to="milan", stance="war"), SendGold(to="milan", amount=10**9))]),
             "bad": FakeSeat([SeatError("agy returned an empty answer")])}
    monkeypatch.setattr(bench, "make_seat", lambda spec: seats[spec])
    good = bench.bench(tmp_path, "good", 5)
    assert "1 kept, 1 rejected, 0 malformed" in good and "set_stance" in good and "REJECTED 1 send_gold" in good
    assert "FAILED SeatError: agy returned an empty answer" in bench.bench(tmp_path, "bad", 5)


def test_a_failed_review_never_disturbs_the_game(tmp_path):
    from parley.seats import SeatError
    cfg = _config(tmp_path)
    orch = Orchestrator(cfg, {"venice": FakeSeat([], chats=[SeatError("down")])})
    past = orch.turns.path_for("test", 20, "venice")
    past.mkdir(parents=True, exist_ok=True)
    (past / "orders.json").write_text(Orders(protocol=1, game_id="test", turn=20, faction="venice",
                                             orders=[], note="n").model_dump_json())
    assert orch.review("venice", 20) == []


def test_a_review_prompt_carries_the_outcomes_from_the_turn_reports(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    prompts = []

    class Seat:
        def chat(self, prompt, *, timeout):
            prompts.append(prompt)
            return '{"lessons": []}'

    orch = Orchestrator(cfg, {"venice": Seat()})
    for turn, treasury in ((1, 100), (20, 900)):
        past = orch.turns.path_for("test", turn, "venice")
        past.mkdir(parents=True, exist_ok=True)
        (past / "orders.json").write_text(Orders(protocol=1, game_id="test", turn=turn, faction="venice",
                                                 orders=[], note=f"note {turn}").model_dump_json())
        (past / "state.json").write_text(json.dumps({**venice_state_dict, "turn": turn, "treasury": treasury}))
    orch.review("venice", 20)
    assert "OUTCOMES" in prompts[0] and "Treasury 100 -> 900" in prompts[0]


def test_turn_decision_log_records_rows(tmp_path, venice_state_dict):
    from jigsaw import DecisionLog
    cfg = _config(tmp_path, ("venice",))
    _pending(cfg, "venice", venice_state_dict, turn=1)
    orders = _orders(SendGold(to="milan", amount=100))
    orch = Orchestrator(cfg, {"venice": FakeSeat([orders])})
    assert orch.run_once() == 1

    db_path = cfg.turn_root / f"{cfg.game_id}.decisions.db"
    assert db_path.exists()
    dlog = DecisionLog(db_path)
    rows = dlog.query(actor="venice")
    assert len(rows) == 1
    assert rows[0].actor == "venice"
    assert rows[0].kind == "send_gold"
    assert rows[0].legality == [{"ok": True, "index": 0}]


def test_turn_decision_log_records_outcomes_after_two_turns(tmp_path, venice_state_dict):
    from jigsaw import DecisionLog
    cfg = _config(tmp_path, ("venice",))
    _pending(cfg, "venice", venice_state_dict, turn=1)
    orders_t1 = _orders(
        SendGold(to="milan", amount=100),
        SendGold(to="milan", amount=99999),
    )
    orders_t2 = _orders()
    orch = Orchestrator(cfg, {"venice": FakeSeat([orders_t1, orders_t2])})
    assert orch.run_once() == 1

    db_path = cfg.turn_root / f"{cfg.game_id}.decisions.db"
    assert db_path.exists()
    dlog = DecisionLog(db_path)
    rows = sorted(dlog.query(actor="venice"), key=lambda d: d.id or 0)
    assert len(rows) == 2
    assert rows[0].outcome is None
    assert rows[1].outcome is None

    turn2_state = {
        **venice_state_dict,
        "turn": 2,
        "last_results": [{"index": 0, "type": "send_gold", "ok": True}],
    }
    _pending(cfg, "venice", turn2_state, turn=2)
    assert orch.run_once() == 1

    t1_decisions = sorted([r for r in dlog.query(actor="venice") if r.turn == 1], key=lambda d: d.id or 0)
    assert len(t1_decisions) == 2
    assert t1_decisions[0].kind == "send_gold"
    assert t1_decisions[0].outcome == "done"
    assert t1_decisions[0].outcome_turn == 2

    assert t1_decisions[1].kind == "send_gold"
    assert t1_decisions[1].outcome.startswith("refused: ")
    assert t1_decisions[1].outcome_turn == 2


def test_record_outcomes_error_does_not_break_turn(tmp_path, venice_state_dict, caplog):
    import logging
    cfg = _config(tmp_path, ("venice",))
    _pending(cfg, "venice", venice_state_dict, turn=1)
    orders = _orders(SendGold(to="milan", amount=100))
    orch = Orchestrator(cfg, {"venice": FakeSeat([orders, _orders()])})
    assert orch.run_once() == 1

    class BrokenOutcomesDecisionLog:
        def query(self, **kwargs):
            raise RuntimeError("simulated query failure")

    orch.decision_log = BrokenOutcomesDecisionLog()

    turn2_state = {
        **venice_state_dict,
        "turn": 2,
        "last_results": [{"index": 0, "type": "send_gold", "ok": True}],
    }
    d2 = _pending(cfg, "venice", turn2_state, turn=2)

    with caplog.at_level(logging.WARNING, logger="parley"):
        assert orch.run_once() == 1

    assert (d2 / "orders.json").exists()
    assert "recording outcomes failed: simulated query failure" in caplog.text


def test_decision_log_error_does_not_break_turn(tmp_path, venice_state_dict, caplog):
    import logging
    cfg = _config(tmp_path, ("venice",))
    d = _pending(cfg, "venice", venice_state_dict, turn=1)
    orders = _orders(SendGold(to="milan", amount=100))
    orch = Orchestrator(cfg, {"venice": FakeSeat([orders])})

    class BrokenDecisionLog:
        def record(self, d):
            raise RuntimeError("simulated decision log failure")

    orch.decision_log = BrokenDecisionLog()

    with caplog.at_level(logging.WARNING, logger="parley"):
        assert orch.run_once() == 1

    assert (d / "orders.json").exists()
    assert "decision log failed: simulated decision log failure" in caplog.text


def test_turn_gate_quiet_turn_answered_by_quiet_seat(tmp_path, venice_state_dict):
    from jigsaw import DecisionLog
    cfg = _config(tmp_path, ("venice",))
    cfg.seats["venice"].ladder = True
    cfg.seats["venice"].quiet_brain = "agy:gemini-3.8-flash-low"
    _pending(cfg, "venice", venice_state_dict, turn=1)

    ruler_seat = FakeSeat([_orders(SendGold(to="milan", amount=999))])
    quiet_seat = FakeSeat([_orders(SendGold(to="milan", amount=100))])
    orch = Orchestrator(cfg, {"venice": ruler_seat}, quiet_seats={"venice": quiet_seat})

    assert orch.run_once() == 1
    assert len(ruler_seat.timeouts) == 0  # ruler seat not called
    assert len(quiet_seat.timeouts) == 1  # quiet seat answered

    dlog = DecisionLog(cfg.turn_root / f"{cfg.game_id}.decisions.db")
    rows = dlog.query(actor="venice")
    gate_rows = [r for r in rows if r.kind == "turn_gate"]
    assert len(gate_rows) == 1
    gate = gate_rows[0]
    assert gate.situation == "quiet turn"
    assert gate.rung == 4
    assert gate.escalated_because == ""
    assert gate.choice == "agy:gemini-3.8-flash-low"

    order_rows = [r for r in rows if r.kind != "turn_gate"]
    assert len(order_rows) == 1
    assert "LLM seat (agy:gemini-3.8-flash-low)" in order_rows[0].escalated_because


def test_turn_gate_non_quiet_turn_goes_to_ruler_with_reason(tmp_path, venice_state_dict):
    from jigsaw import DecisionLog
    cfg = _config(tmp_path, ("venice",))
    cfg.seats["venice"].ladder = True
    cfg.seats["venice"].quiet_brain = "agy:gemini-3.8-flash-low"
    # turn 5 triggers "cadence"
    _pending(cfg, "venice", {**venice_state_dict, "turn": 5}, turn=5)

    ruler_seat = FakeSeat([_orders(SendGold(to="milan", amount=500))])
    quiet_seat = FakeSeat([_orders(SendGold(to="milan", amount=100))])
    orch = Orchestrator(cfg, {"venice": ruler_seat}, quiet_seats={"venice": quiet_seat})

    assert orch.run_once() == 1
    assert len(quiet_seat.timeouts) == 0  # quiet seat not called
    assert len(ruler_seat.timeouts) == 1  # ruler answered

    dlog = DecisionLog(cfg.turn_root / f"{cfg.game_id}.decisions.db")
    gate_rows = [r for r in dlog.query(actor="venice") if r.kind == "turn_gate"]
    assert len(gate_rows) == 1
    gate = gate_rows[0]
    assert gate.situation == "cadence"
    assert gate.rung == 5
    assert gate.escalated_because == "cadence"
    assert gate.choice == cfg.seats["venice"].brain


def test_turn_gate_quiet_seat_failure_falls_back_to_ruler(tmp_path, venice_state_dict):
    from jigsaw import DecisionLog
    cfg = _config(tmp_path, ("venice",))
    cfg.seats["venice"].ladder = True
    cfg.seats["venice"].quiet_brain = "agy:gemini-3.8-flash-low"
    _pending(cfg, "venice", venice_state_dict, turn=1)

    ruler_seat = FakeSeat([_orders(SendGold(to="milan", amount=500))])
    quiet_seat = FakeSeat([SeatError("quiet brain timed out")])
    orch = Orchestrator(cfg, {"venice": ruler_seat}, quiet_seats={"venice": quiet_seat})

    assert orch.run_once() == 1
    assert len(quiet_seat.timeouts) == 1
    assert len(ruler_seat.timeouts) == 1  # ruler called after quiet failure

    dlog = DecisionLog(cfg.turn_root / f"{cfg.game_id}.decisions.db")
    gate_rows = [r for r in dlog.query(actor="venice") if r.kind == "turn_gate"]
    assert len(gate_rows) == 1
    gate = gate_rows[0]
    assert gate.situation == "quiet turn"
    assert gate.rung == 5
    assert gate.choice == cfg.seats["venice"].brain


def test_turn_gate_quiet_seat_no_orders_falls_back_to_ruler(tmp_path, venice_state_dict):
    from jigsaw import DecisionLog
    cfg = _config(tmp_path, ("venice",))
    cfg.seats["venice"].ladder = True
    cfg.seats["venice"].quiet_brain = "agy:gemini-3.8-flash-low"
    _pending(cfg, "venice", venice_state_dict, turn=1)

    ruler_seat = FakeSeat([_orders(SendGold(to="milan", amount=500))])
    quiet_seat = FakeSeat([_orders()])  # empty orders
    orch = Orchestrator(cfg, {"venice": ruler_seat}, quiet_seats={"venice": quiet_seat})

    assert orch.run_once() == 1
    assert len(quiet_seat.timeouts) == 1
    assert len(ruler_seat.timeouts) == 1  # ruler called after quiet empty orders


def test_turn_gate_un_gated_seat_never_touches_gate(tmp_path, venice_state_dict):
    from jigsaw import DecisionLog
    cfg = _config(tmp_path, ("venice",))
    # ladder is False, quiet_brain is set
    cfg.seats["venice"].ladder = False
    cfg.seats["venice"].quiet_brain = "agy:gemini-3.8-flash-low"
    _pending(cfg, "venice", venice_state_dict, turn=1)

    ruler_seat = FakeSeat([_orders(SendGold(to="milan", amount=100))])
    quiet_seat = FakeSeat([_orders(SendGold(to="milan", amount=200))])
    orch = Orchestrator(cfg, {"venice": ruler_seat}, quiet_seats={"venice": quiet_seat})

    assert orch.run_once() == 1
    assert len(quiet_seat.timeouts) == 0
    assert len(ruler_seat.timeouts) == 1

    dlog = DecisionLog(cfg.turn_root / f"{cfg.game_id}.decisions.db")
    rows = dlog.query(actor="venice")
    assert not any(r.kind == "turn_gate" for r in rows)


def test_turn_gate_streak_forces_ruler_on_third_quiet_turn(tmp_path, venice_state_dict):
    from jigsaw import DecisionLog
    cfg = _config(tmp_path, ("venice",))
    cfg.seats["venice"].ladder = True
    cfg.seats["venice"].quiet_brain = "agy:gemini-3.8-flash-low"

    ruler_seat = FakeSeat([
        _orders(SendGold(to="milan", amount=300)),
    ])
    quiet_seat = FakeSeat([
        _orders(SendGold(to="milan", amount=100)),
        _orders(SendGold(to="milan", amount=200)),
    ])
    orch = Orchestrator(cfg, {"venice": ruler_seat}, quiet_seats={"venice": quiet_seat})

    # Turn 1: quiet turn -> quiet seat
    _pending(cfg, "venice", {**venice_state_dict, "turn": 1}, turn=1)
    assert orch.run_once() == 1
    assert len(quiet_seat.timeouts) == 1
    assert len(ruler_seat.timeouts) == 0
    assert orch._quiet_streaks["venice"] == 1

    # Turn 2: quiet turn -> quiet seat
    _pending(cfg, "venice", {**venice_state_dict, "turn": 2}, turn=2)
    assert orch.run_once() == 1
    assert len(quiet_seat.timeouts) == 2
    assert len(ruler_seat.timeouts) == 0
    assert orch._quiet_streaks["venice"] == 2

    # Turn 3: quiet_streak == 2 >= max_streak (2) -> "streak", forces ruler!
    _pending(cfg, "venice", {**venice_state_dict, "turn": 3}, turn=3)
    assert orch.run_once() == 1
    assert len(quiet_seat.timeouts) == 2  # quiet seat NOT called on turn 3
    assert len(ruler_seat.timeouts) == 1  # ruler called
    assert orch._quiet_streaks["venice"] == 0  # streak resets

    dlog = DecisionLog(cfg.turn_root / f"{cfg.game_id}.decisions.db")
    t3_gate = [r for r in dlog.query(actor="venice") if r.turn == 3 and r.kind == "turn_gate"][0]
    assert t3_gate.situation == "streak"
    assert t3_gate.rung == 5
    assert t3_gate.escalated_because == "streak"
    assert t3_gate.choice == cfg.seats["venice"].brain


def test_turn_gate_caches_quiet_seat_with_make_seat(tmp_path, venice_state_dict, monkeypatch):
    cfg = _config(tmp_path, ("venice",))
    cfg.seats["venice"].ladder = True
    cfg.seats["venice"].quiet_brain = "fake:custom"
    _pending(cfg, "venice", venice_state_dict, turn=1)

    built_seats = []
    fake_quiet = FakeSeat([_orders(SendGold(to="milan", amount=100))])

    def mock_make_seat(spec: str, budget=None):
        built_seats.append(spec)
        return fake_quiet

    monkeypatch.setattr("parley.orchestrator.make_seat", mock_make_seat)

    ruler_seat = FakeSeat([])
    orch = Orchestrator(cfg, {"venice": ruler_seat})  # quiet_seats not passed

    assert orch.run_once() == 1
    assert built_seats == ["fake:custom"]
    assert orch._quiet_seats["venice"] is fake_quiet
    assert len(fake_quiet.timeouts) == 1


def test_each_new_turn_is_audited_alerted_and_told_to_the_ruler(tmp_path, venice_state_dict):
    # the author, 2026-10-29: problems sat in the turn folders until he asked
    cfg = _config(tmp_path)
    _pending(cfg, "venice", {**venice_state_dict, "treasury": 100, "income": -90}, turn=1)
    orch = Orchestrator(cfg, {"venice": FakeSeat()})
    orch.run_once()
    d2 = TurnDir(cfg.turn_root).path_for(cfg.game_id, 2, "venice")
    d2.mkdir(parents=True, exist_ok=True)
    (d2 / "state.json").write_text(json.dumps({**venice_state_dict, "turn": 2}))
    orch.run_once()
    prompt = (d2 / "prompt.txt").read_text()
    assert "Your money is running out: treasury 100, income -90 a turn: 1 turns left." in prompt
    assert "The disband order releases units" in prompt
    alerts = [m.text for m in orch.store.unposted(cfg.game_id) if m.channel == "audit"]
    assert any("[ruler] money running out (venice)" in a for a in alerts)
    # the next turn's audit doesn't repeat what was already alerted
    before = len(alerts)
    d3 = TurnDir(cfg.turn_root).path_for(cfg.game_id, 3, "venice")
    d3.mkdir(parents=True, exist_ok=True)
    (d3 / "state.json").write_text(json.dumps({**venice_state_dict, "turn": 3}))
    orch.run_once()
    assert len([m for m in orch.store.unposted(cfg.game_id) if m.channel == "audit"]) == before



class GatedSeat:
    """A seat that says it started and answers only when the test lets it (events, no timing)."""

    name = "gated"

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def decide(self, prompt, *, game_id, turn, faction, timeout):
        self.started.set()
        assert self.release.wait(10), "the test never released the seat"
        return FakeSeat().decide(prompt, game_id=game_id, turn=turn, faction=faction, timeout=timeout)

    def chat(self, prompt, *, timeout):
        return ""


def _poll_until_answered(orch, want):
    got, deadline = 0, time.monotonic() + 10
    while got < want and time.monotonic() < deadline:
        got += orch.run_once(wait=False)
        time.sleep(0.01)
    return got


def test_a_report_landing_while_another_seat_thinks_starts_at_once(tmp_path, venice_state_dict):
    """Live 2026-10-30: France's report came 17 s after England's; France started only after
    England's 352 s turn ended, and the bridge gave up on it."""
    cfg = _config(tmp_path, ("venice", "milan"))
    slow, quick = GatedSeat(), GatedSeat()
    orch = Orchestrator(cfg, {"venice": slow, "milan": quick})
    venice_dir = _pending(cfg, "venice", venice_state_dict)
    assert orch.run_once(wait=False) == 0
    assert slow.started.wait(10)
    milan_dir = _pending(cfg, "milan", venice_state_dict)  # arrives while venice is still deciding
    assert orch.run_once(wait=False) == 0
    assert quick.started.wait(10)  # started with venice still running
    quick.release.set()  # milan answers first; venice is still out
    assert _poll_until_answered(orch, 1) == 1
    assert (milan_dir / "orders.json").exists() and not (venice_dir / "orders.json").exists()
    slow.release.set()
    assert _poll_until_answered(orch, 1) == 1
    assert (venice_dir / "orders.json").exists() and orch._inflight == {}


def test_a_running_seat_is_not_started_twice(tmp_path, venice_state_dict):
    cfg = _config(tmp_path)
    seat = GatedSeat()
    orch = Orchestrator(cfg, {"venice": seat})
    _pending(cfg, "venice", venice_state_dict)
    orch.run_once(wait=False)
    assert seat.started.wait(10)
    for _ in range(3):
        orch.run_once(wait=False)
    assert len(orch._inflight) == 1
    seat.release.set()
    assert _poll_until_answered(orch, 1) == 1


def test_bridge_config_carries_the_papal_hands_off_switch(tmp_path):
    from parley.config import AutoplayConfig
    cfg = _config(tmp_path, ("venice",)).model_copy(update={"autoplay": AutoplayConfig()})
    Orchestrator(cfg, {}).publish_bridge_config()
    assert "papal_hands_off=1" in (cfg.turn_root / "bridge.txt").read_text().splitlines()  # on by default
    cfg = cfg.model_copy(update={"autoplay": AutoplayConfig(papal_hands_off=False)})  # a game toml can turn it off
    Orchestrator(cfg, {}).publish_bridge_config()
    assert "papal_hands_off=1" not in (cfg.turn_root / "bridge.txt").read_text().splitlines()
