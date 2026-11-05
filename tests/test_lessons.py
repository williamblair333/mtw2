"""Lessons across games: the store, the review prompt and its parsing (drafted by Gemini, reviewed)."""

import json

from parley.lessons import Lesson, active, add, code_version, key_for, load, parse_review, review_prompt, veto


def _add(root, key, items, turn=8, game_id="g1", version="abc1234", today="2026-10-25"):
    return add(root, key, items, game_id=game_id, turn=turn, version=version, today=today)


def test_key_for():
    assert key_for("Old Scratch") == "old-scratch"
    assert key_for("Doge Enrico Dandolo!") == "doge-enrico-dandolo"
    assert key_for("") == "unnamed"
    assert key_for("   !!!   ") == "unnamed"
    assert key_for("  King   Henry II  ") == "king-henry-ii"


def test_add_and_load_round_trip(tmp_path):
    added = _add(tmp_path, "old-scratch", [
        {"text": "Build roads before barracks.", "evidence": "Turns 3-5"},
        {"text": "   ", "evidence": "Ignored empty"},
        {"text": "Keep a garrison in frontier castles.", "evidence": "Turn 7"},
    ])
    assert len(added) == 2 and all(isinstance(x, Lesson) for x in added)
    a = added[0]
    assert (len(a.id), a.game_id, a.turn, a.version, a.created, a.vetoed) == (8, "g1", 8, "abc1234", "2026-10-25", False)
    assert load(tmp_path, "old-scratch") == added


def test_duplicate_text_skipped(tmp_path):
    assert len(_add(tmp_path, "old-scratch", [{"text": "Never fight a two-front war.", "evidence": "Turn 4"}])) == 1
    assert _add(tmp_path, "old-scratch", [{"text": "  never   FIGHT a   two-front war. \n"}], game_id="g2") == []
    assert len(load(tmp_path, "old-scratch")) == 1


def test_vetoed_lesson_not_added_again(tmp_path):
    added = _add(tmp_path, "old-scratch", [{"text": "Bribe rebel captains early.", "evidence": "Turn 2"}])
    vetoed = veto(tmp_path, added[0].id)
    assert vetoed is not None and vetoed.vetoed
    assert _add(tmp_path, "old-scratch", [{"text": "bribe   rebel captains EARLY."}], game_id="g2") == []
    stored = load(tmp_path, "old-scratch")
    assert len(stored) == 1 and stored[0].vetoed


def test_active_order_limit_and_vetoed_excluded(tmp_path):
    added = _add(tmp_path, "old-scratch", [{"text": f"Lesson number {i}", "evidence": f"Turn {i}"} for i in range(1, 8)])
    veto(tmp_path, added[5].id)  # "Lesson number 6"
    assert [x.text for x in active(tmp_path, "old-scratch", limit=3)] == [
        "Lesson number 7", "Lesson number 5", "Lesson number 4"]
    default = active(tmp_path, "old-scratch")
    assert len(default) == 5 and not any(x.vetoed for x in default)


def test_veto_across_files_and_unknown_id(tmp_path):
    _add(tmp_path, "ruler-one", [{"text": "Tax ports heavily."}])
    two = _add(tmp_path, "ruler-two", [{"text": "Use merchants on silk."}])
    res = veto(tmp_path, two[0].id)
    assert res is not None and res.id == two[0].id and res.vetoed
    assert not load(tmp_path, "ruler-one")[0].vetoed and load(tmp_path, "ruler-two")[0].vetoed
    assert veto(tmp_path, "deadbeef") is None
    assert veto(tmp_path / "nowhere", "deadbeef") is None


def test_load_corrupt_and_missing_files(tmp_path):
    assert load(tmp_path, "missing") == []
    (tmp_path / "corrupt.json").write_text("{not valid json", encoding="utf-8")
    assert load(tmp_path, "corrupt") == []
    (tmp_path / "partial.json").write_text(json.dumps([
        {"id": "12345678", "text": "Valid lesson"}, {"bad": "item_missing_required_fields"}]), encoding="utf-8")
    loaded = load(tmp_path, "partial")
    assert [x.id for x in loaded] == ["12345678"]


def test_review_prompt_contents():
    prompt = review_prompt("Old Scratch", "Venice", [
        (12, "Marching north toward Milan.", ["order 2 (attack): REJECTED: target not in sight"])])
    for want in ("Old Scratch", "Venice", "TURN 12", "Marching north toward Milan.",
                 "order 2 (attack): REJECTED: target not in sight", "not lessons"):
        assert want in prompt


def test_parse_review_variants():
    fenced = '```json\n{"lessons": [{"text": "Scout before marching.", "evidence": "Turn 12"}]}\n```'
    assert parse_review(fenced) == [{"text": "Scout before marching.", "evidence": "Turn 12"}]
    prose = ('Here are the lessons from the review:\n'
             '{"lessons": [{"text": "Hold river crossings.", "evidence": "Turns 4-6"}]}\nHope this helps!')
    assert parse_review(prose) == [{"text": "Hold river crossings.", "evidence": "Turns 4-6"}]
    assert parse_review("completely malformed garbage {{{") == []
    assert parse_review('{"wrong_key": []}') == []
    assert parse_review('{"lessons": [{"text": 123}]}') == []


def test_code_version_outside_repo(tmp_path):
    assert code_version(tmp_path) == ""
