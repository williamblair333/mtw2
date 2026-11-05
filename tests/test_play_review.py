"""Tests for the play reviewer (digests, prompt, review, and CLI)."""

from datetime import datetime
import json
from pathlib import Path

import pytest

from parley.play_review import main, review, review_prompt, turn_digest


def test_a_review_of_five_big_turns_fits_one_agy_argument(tmp_path):
    # live: five whole 60 KB prompts failed with "Argument list too long"; Linux caps one argument at 128 KB
    big = ("PERSONA\n" + "x" * 9000 + "\nYOUR SETTLEMENTS\n" + "s" * 40000
           + "\nLAST TURN'S ORDER RESULTS\n" + "r" * 20000 + "\nOUTPUT RULES\n" + "o" * 6000)
    for t in range(1, 6):
        d = tmp_path / "g" / f"turn-{t:04d}" / "england"
        d.mkdir(parents=True)
        (d / "prompt.txt").write_text(big)
        (d / "results.json").write_text("[]")
    seat = FakeReviewSeat()
    assert review(tmp_path, "g", "england", 5, 5, seat) == "REVIEW"
    prompt = seat.recorded_prompt
    assert len(prompt.encode()) < 110_000
    assert "PERSONA" not in prompt and "OUTPUT RULES" not in prompt
    assert prompt.count("YOUR SETTLEMENTS") == 1  # the newest turn's state only


class FakeReviewSeat:
    def __init__(self):
        self.recorded_prompt = ""
        self.recorded_timeout = None

    def chat(self, prompt: str, *, timeout: float = 600) -> str:
        self.recorded_prompt = prompt
        self.recorded_timeout = timeout
        return "REVIEW"


@pytest.fixture
def two_turns(tmp_path):
    root = tmp_path / "turns"
    game_id = "g1"
    faction = "venice"
    t1 = root / game_id / "turn-0001" / faction
    t2 = root / game_id / "turn-0002" / faction
    t1.mkdir(parents=True, exist_ok=True)
    t2.mkdir(parents=True, exist_ok=True)

    # Turn 1: normal turn, missing answer.txt and rejected.json
    (t1 / "prompt.txt").write_text("Prompt turn 1: 5000 florins treasury, Milan is neutral.", encoding="utf-8")
    (t1 / "orders.json").write_text(json.dumps({"orders": [{"type": "build", "building": "roads"}]}), encoding="utf-8")
    (t1 / "results.json").write_text(json.dumps([{"type": "build", "ok": True}]), encoding="utf-8")

    # Turn 2: includes a refused order and rejected.json
    (t2 / "prompt.txt").write_text("Prompt turn 2: Milan is hostile, siege at Genoa.", encoding="utf-8")
    (t2 / "orders.json").write_text(json.dumps({"orders": [{"type": "attack", "target": "Milan"}]}), encoding="utf-8")
    (t2 / "results.json").write_text(
        json.dumps([{"type": "attack", "ok": False, "reason": "target not in sight"}]), encoding="utf-8"
    )
    (t2 / "rejected.json").write_text(
        json.dumps([{"type": "attack", "reason": "target not in sight"}]), encoding="utf-8"
    )

    return root, game_id, faction, t1, t2


def test_turn_digest_includes_files_and_skips_missing(two_turns):
    root, game_id, faction, t1, t2 = two_turns
    digest = turn_digest(t1, faction)

    assert "### prompt.txt" in digest
    assert "5000 florins treasury" in digest
    assert "### orders.json" in digest
    assert "roads" in digest
    assert "### results.json" in digest
    # Missing files must be skipped silently
    assert "### answer.txt" not in digest
    assert "### rejected.json" not in digest


def test_turn_digest_prompt_truncation(two_turns):
    root, game_id, faction, t1, t2 = two_turns
    digest = turn_digest(t1, faction, max_prompt_chars=13)

    # Prompt starts with "Prompt turn 1" (13 chars)
    assert "Prompt turn 1" in digest
    assert "5000 florins" not in digest


def test_review_includes_both_turns_and_returns_review(two_turns):
    root, game_id, faction, t1, t2 = two_turns
    seat = FakeReviewSeat()

    res = review(root, game_id, faction, last_turn=2, span=2, seat=seat)
    assert res == "REVIEW"
    assert seat.recorded_timeout == 600

    prompt = seat.recorded_prompt
    assert "Turn 1" in prompt
    assert "Turn 2" in prompt
    assert "5000 florins treasury" in prompt
    assert "target not in sight" in prompt
    assert "ruler judgement" in prompt
    assert "under 600 words" in prompt


def test_main_once_writes_expected_file(tmp_path, two_turns, monkeypatch):
    root, game_id, faction, t1, t2 = two_turns
    seat = FakeReviewSeat()
    monkeypatch.setattr("parley.play_review.make_seat", lambda spec: seat)

    class FakeConfig:
        turn_root = root
        game_id = "g1"

    monkeypatch.setattr("parley.play_review.load_config", lambda path: FakeConfig())

    out_dir = tmp_path / "_review"
    cfg_file = tmp_path / "game.toml"
    cfg_file.write_text("game_id = 'g1'\n", encoding="utf-8")

    argv = [str(cfg_file), faction, "--every", "2", "--once", "--out", str(out_dir), "--model", "fake:model"]
    ret = main(argv)
    assert ret == 0

    today = datetime.now().strftime("%Y-%m-%d")
    expected_path = out_dir / f"{today}-play-review-g1-venice-t0002.md"
    assert expected_path.is_file()

    content = expected_path.read_text(encoding="utf-8")
    assert content.startswith("# Play review: fake:model (turns 1..2)")
    assert "REVIEW" in content
