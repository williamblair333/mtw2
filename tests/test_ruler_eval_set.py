"""games/ruler_eval: the fixed scenario set stays readable, and `--set` runs every scenario in it."""

from pathlib import Path

from parley.protocol import StateReport
from parley.ruler_eval import main
from parley.seats.fake import FakeSeat

SET = Path(__file__).parent.parent / "games" / "ruler_eval"


def test_every_committed_scenario_still_parses_as_a_report():
    scenarios = sorted(p.parent for p in SET.glob("*/state.json"))
    assert len(scenarios) == 6
    for s in scenarios:
        report = StateReport.model_validate_json((s / "state.json").read_text(encoding="utf-8"))
        assert report.faction in ("england", "france") and report.settlements
        assert "orders" in (s / "prompt.txt").read_text(encoding="utf-8")


def test_the_kept_orders_are_counted_by_area():
    from parley.protocol import Orders
    from parley.ruler_eval import evaluate, format_table

    class Seat:
        def decide(self, prompt, *, game_id, turn, faction, timeout):
            s = StateReport.model_validate_json((SET / "run9-76-england" / "state.json").read_text())
            town = s.settlements[0].id
            return Orders.model_validate({"protocol": 1, "game_id": game_id, "turn": turn, "faction": faction,
                                          "orders": [{"type": "set_tax", "settlement": town, "level": "low"}]}), ""

    result = evaluate([SET / "run9-76-england"], ["s"], timeout=5, seat_factory=lambda spec: Seat())
    assert result["specs"]["s"]["mix"] == {"taxes": 1}
    assert "| s | 0 | 0 | 0 | 0 | 0 | 1 |" in format_table(result)


def test_set_runs_each_scenario_once_per_seat(tmp_path, monkeypatch, capsys):
    import parley.ruler_eval as ruler_eval
    seen = []

    def fake_evaluate(scenarios, specs, timeout, **_):
        seen.extend(scenarios)
        return {"specs": specs, "scenarios": [s.name for s in scenarios], "results": []}

    monkeypatch.setattr(ruler_eval, "evaluate", fake_evaluate)
    monkeypatch.setattr(ruler_eval, "format_table", lambda r: "table")
    assert main(["--set", str(SET), "--out", str(tmp_path), "fake"]) == 0
    assert [p.name for p in seen] == sorted(p.parent.name for p in SET.glob("*/state.json"))
    assert FakeSeat  # the fake seat spec exists for a real dry run
