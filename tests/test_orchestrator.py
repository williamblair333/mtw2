import json
import time

from parley.bridge import TurnDir
from parley.config import GameConfig, SeatConfig, load_config
from parley.orchestrator import Orchestrator
from parley.protocol import Orders, SendGold, SetStance
from parley.seats import FakeSeat, SeatError


def _config(tmp_path, factions=("venice",)):
    (tmp_path / "saves").mkdir(exist_ok=True)
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


def test_the_session_limit_wording_counts_as_a_usage_limit():
    from parley.seats.claude_code import LIMIT
    assert LIMIT.search("You've hit your session limit · resets 4pm (America/Indiana/Indianapolis)")
    assert LIMIT.search("You've hit your limit") and LIMIT.search("Claude AI usage limit reached")
    assert not LIMIT.search("claude exit 1: model not found")


def test_settlements_seen_on_earlier_turns_are_remembered(tmp_path, venice_state_dict):
    # the adviser, live: "have you fully explored Ireland and England?"
    from parley.protocol import StateReport
    cfg = _config(tmp_path)
    cork = {"id": "Cork", "name": "Cork", "faction": "slave", "x": 80, "y": 160, "garrison_strength": 400}
    d = _pending(cfg, "venice", {**venice_state_dict, "turn": 3, "nearby_settlements": [cork]}, turn=3)
    (d / "orders.json").write_text("{}")
    now = StateReport.model_validate({**venice_state_dict, "turn": 5, "nearby_settlements": []})
    orch = Orchestrator(cfg, {"venice": FakeSeat()})
    [seen] = orch._remembered(now)
    assert (seen.id, seen.seen_turn, seen.garrison_strength) == ("Cork", 3, 400)
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
    (cfg.save_dir / "campaign.sav").write_text("save")
    _pending(cfg, "venice", venice_state_dict)
    Orchestrator(cfg, {"venice": FakeSeat()}).run_once()
    assert [p.name for p in cfg.backup_dir.iterdir()] == ["turn-0001-venice-campaign.sav"]


def test_parallel_seats(tmp_path, venice_state_dict):
    cfg = _config(tmp_path, ("venice", "milan"))
    for f in ("venice", "milan"):
        _pending(cfg, f, venice_state_dict)
    orch = Orchestrator(cfg, {f: FakeSeat(delay=1.0) for f in ("venice", "milan")})
    start = time.monotonic()
    orch.run_once()
    assert time.monotonic() - start < 1.8


def test_load_config(tmp_path):
    p = tmp_path / "g.toml"
    p.write_text(
        'game_id = "g1"\nturn_root = "runs/turns"\nsave_dir = "saves"\n'
        '[seats.venice]\nbrain = "claude:sonnet"\npersona = "Doge."\n'
    )
    cfg = load_config(p)
    assert cfg.seats["venice"].brain == "claude:sonnet"
    assert cfg.turn_root == tmp_path / "runs" / "turns"
    assert cfg.seat_timeout == 120 and cfg.keep_backups == 20


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
    (cfg.save_dir / "campaign.sav").write_text("save")
    for f in ("venice", "milan"):
        _pending(cfg, f, venice_state_dict)
    Orchestrator(cfg, {f: FakeSeat() for f in ("venice", "milan")}).run_once()
    assert len(list(cfg.backup_dir.iterdir())) == 1


def test_run_forever_survives_errors(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    orch = Orchestrator(cfg, {"venice": FakeSeat()})
    calls = []

    def flaky():
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
    assert "order 0 (send_gold): REJECTED" in prompt
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
    assert lines[-3:] == ["autoplay=1", "autoplay_wait=90", "autoplay_until=30"]


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
    assert "order 0 (set_stance): REJECTED: arrived too late" in (d2 / "prompt.txt").read_text()


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
