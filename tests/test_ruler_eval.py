import json
from pathlib import Path

from parley.protocol import FactionView, Orders, SetStance, StateReport
from parley.ruler_eval import evaluate, format_table, main
from parley.seats.fake import FakeSeat


def make_scenario(tmp_path: Path, name: str = "t70-england") -> Path:
    dest = tmp_path / name  # a synthetic turn: tests never read files outside the repo
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "prompt.txt").write_text("SCENARIO\nMinimal test prompt", encoding="utf-8")
    report = StateReport(
        protocol=1,
        game_id="game-1",
        turn=70 if "70" in name else 72,
        year=1100,
        faction="england",
        treasury=50000,
        income=1000,
        settlements=[],
        armies=[],
        factions=[FactionView(id="france", name="France", stance="peace")],
        visible_enemies=[],
        last_results=[],
    )
    (dest / "state.json").write_text(report.model_dump_json(), encoding="utf-8")
    return dest


def test_seat_whose_orders_all_validate(tmp_path):
    sc1 = make_scenario(tmp_path, "t70-england")
    sc2 = make_scenario(tmp_path, "t72-england")
    valid_orders = Orders(
        protocol=1,
        game_id="game-1",
        turn=70,
        faction="england",
        orders=[SetStance(to="france", stance="war")],
        note="good orders note",
    )
    seat = FakeSeat(script=[valid_orders, valid_orders])
    res = evaluate([sc1, sc2], ["good_seat"], timeout=10.0, seat_factory=lambda _: seat)

    assert len(res["runs"]) == 2
    for r in res["runs"]:
        assert r["ok"] is True
        assert r["kept"] == 1
        assert r["rejected"] == 0
        assert r["malformed"] == 0
        assert r["has_note"] is True
        assert r["error"] == ""

    spec_summary = res["specs"]["good_seat"]
    assert spec_summary["runs"] == 2
    assert spec_summary["answered"] == 2
    assert spec_summary["kept"] == 2
    assert spec_summary["rejected"] == 0
    assert spec_summary["malformed"] == 0
    assert spec_summary["legal_rate"] == 1.0
    assert spec_summary["median_seconds"] >= 0.0
    assert spec_summary["max_seconds"] >= 0.0


def test_seat_that_raises(tmp_path):
    sc1 = make_scenario(tmp_path, "t70-england")
    seat = FakeSeat(script=[RuntimeError("seat crashed")])
    res = evaluate([sc1], ["failing_seat"], timeout=10.0, seat_factory=lambda _: seat)

    assert len(res["runs"]) == 1
    run = res["runs"][0]
    assert run["ok"] is False
    assert "seat crashed" in run["error"]
    assert run["kept"] == 0
    assert run["rejected"] == 0
    assert run["malformed"] == 0
    assert run["has_note"] is False

    spec_summary = res["specs"]["failing_seat"]
    assert spec_summary["runs"] == 1
    assert spec_summary["answered"] == 0
    assert spec_summary["kept"] == 0
    assert spec_summary["legal_rate"] is None


def test_legal_rate_math_and_none_when_no_orders(tmp_path):
    sc = make_scenario(tmp_path, "t70-england")

    # 1. No orders -> legal_rate is None
    empty_orders = Orders(protocol=1, game_id="game-1", turn=70, faction="england", orders=[])
    seat_empty = FakeSeat(script=[empty_orders])
    res_empty = evaluate([sc], ["empty_seat"], timeout=10.0, seat_factory=lambda _: seat_empty)
    assert res_empty["specs"]["empty_seat"]["legal_rate"] is None
    assert res_empty["specs"]["empty_seat"]["kept"] == 0

    # 2. Mixed orders: 1 valid, 1 rejected
    mixed_orders = Orders(
        protocol=1,
        game_id="game-1",
        turn=70,
        faction="england",
        orders=[
            SetStance(to="france", stance="war"),
            SetStance(to="unknown_faction", stance="war"),
        ],
    )
    seat_mixed = FakeSeat(script=[mixed_orders])
    res_mixed = evaluate([sc], ["mixed_seat"], timeout=10.0, seat_factory=lambda _: seat_mixed)
    summary = res_mixed["specs"]["mixed_seat"]
    assert summary["kept"] == 1
    assert summary["rejected"] == 1
    assert summary["malformed"] == 0
    assert summary["legal_rate"] == 0.5


def test_format_table_includes_every_spec():
    result = {
        "runs": [
            {
                "spec": "seat_a",
                "scenario": "t70",
                "seconds": 1.2,
                "ok": True,
                "error": "",
                "kept": 5,
                "rejected": 1,
                "malformed": 0,
                "has_note": True,
            },
            {
                "spec": "seat_b",
                "scenario": "t70",
                "seconds": 0.5,
                "ok": False,
                "error": "TimeoutError: timed out",
                "kept": 0,
                "rejected": 0,
                "malformed": 0,
                "has_note": False,
            },
        ],
        "specs": {
            "seat_a": {
                "runs": 1,
                "answered": 1,
                "kept": 5,
                "rejected": 1,
                "malformed": 0,
                "legal_rate": 5 / 6,
                "median_seconds": 1.2,
                "max_seconds": 1.2,
            },
            "seat_b": {
                "runs": 1,
                "answered": 0,
                "kept": 0,
                "rejected": 0,
                "malformed": 0,
                "legal_rate": None,
                "median_seconds": 0.5,
                "max_seconds": 0.5,
            },
        },
    }
    table = format_table(result)
    assert "seat_a" in table
    assert "seat_b" in table
    assert "83.3%" in table
    assert "FAILED seat_b t70: TimeoutError: timed out" in table


def test_main_writes_both_files(tmp_path, monkeypatch):
    sc = make_scenario(tmp_path, "t70-england")
    out_dir = tmp_path / "eval_out"
    orders = Orders(
        protocol=1,
        game_id="game-1",
        turn=70,
        faction="england",
        orders=[SetStance(to="france", stance="war")],
    )
    fake_seat = FakeSeat(script=[orders])

    import parley.ruler_eval as re_mod
    orig_eval = re_mod.evaluate

    def patched_evaluate(scenarios, specs, timeout, seat_factory=None):
        return orig_eval(scenarios, specs, timeout, seat_factory=lambda _: fake_seat)

    monkeypatch.setattr(re_mod, "evaluate", patched_evaluate)

    argv = ["--scenario", str(sc), "--out", str(out_dir), "fake:seat"]
    ret = main(argv)
    assert ret == 0

    json_files = list(out_dir.glob("*.json"))
    md_files = list(out_dir.glob("*.md"))
    assert len(json_files) == 1
    assert len(md_files) == 1

    data = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert "runs" in data
    assert "specs" in data
    assert "fake:seat" in data["specs"]

    md_text = md_files[0].read_text(encoding="utf-8")
    assert "fake:seat" in md_text
