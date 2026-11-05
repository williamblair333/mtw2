"""Tests for parley.decisions_report."""

from jigsaw import Decision, DecisionLog
from parley.decisions_report import main, summarize


def test_summarize_counts_ordering_percentage_filtering_and_truncation(tmp_path):
    db_path = tmp_path / "test.decisions.db"
    with DecisionLog(db_path) as log:
        # Decisions for game "g1":
        # 4 decisions, across 2 rungs (rung 2, rung 7: 50% each), 2 kinds (attack, send_gold),
        # 2 actors (milan, venice), turns 1..3.
        # One with outcome (d2), one escalated (d4), one truncated (d3).
        d1 = Decision(
            game="g1",
            turn=1,
            actor="venice",
            kind="send_gold",
            rung=2,
            situation="situation 1",
            choice="give 100 gold",
        )
        d2 = Decision(
            game="g1",
            turn=1,
            actor="milan",
            kind="attack",
            rung=7,
            situation="situation 2",
            choice="attack gate",
            outcome="done",
            outcome_turn=2,
        )
        d3 = Decision(
            game="g1",
            turn=2,
            actor="venice",
            kind="attack",
            rung=7,
            situation="situation 3",
            choice="A" * 200,
        )
        d4 = Decision(
            game="g1",
            turn=3,
            actor="milan",
            kind="send_gold",
            rung=2,
            situation="situation 4",
            choice="tribute 50",
            escalated_because="LLM seat",
        )
        for d in (d1, d2, d3, d4):
            log.record(d)

        # Another game to verify game filtering
        d_other = Decision(
            game="other_game",
            turn=1,
            actor="france",
            kind="bribe",
            rung=7,
            situation="other situation",
            choice="bribe captain",
        )
        log.record(d_other)

        text = summarize(log, "g1", last=20)

        # Header check: game, total decisions, turns covered (min..max)
        assert "g1: 4 decisions, turns 1..3" in text

        # Game filtering: other game decisions must not appear
        assert "other_game" not in text
        assert "france" not in text
        assert "bribe" not in text

        # By rung: present rungs ascending (2, then 7), count and percentage (50% each)
        assert "By rung:" in text
        assert "rung 2: 2 (50%)" in text
        assert "rung 7: 2 (50%)" in text
        assert text.index("rung 2:") < text.index("rung 7:")

        # By kind: count per kind, and how many have an outcome recorded
        assert "By kind:" in text
        assert "attack: 2 (1 with outcome)" in text
        assert "send_gold: 2 (0 with outcome)" in text

        # By actor: count per actor
        assert "By actor:" in text
        assert "milan: 2" in text
        assert "venice: 2" in text

        # Latest N: newest first
        assert "Latest 4:" in text
        idx_d4 = text.index("t3 milan send_gold rung 2: tribute 50 (escalated: LLM seat)")
        idx_d3 = text.index("t2 venice attack rung 7:")
        idx_d2 = text.index("t1 milan attack rung 7: attack gate -> done")
        idx_d1 = text.index("t1 venice send_gold rung 2: give 100 gold")
        assert idx_d4 < idx_d3 < idx_d2 < idx_d1

        # Outcome and escalation formatting
        assert "-> done" in text
        assert "(escalated: LLM seat)" in text

        # Truncation: d3 line is truncated to 160 characters
        d3_lines = [l for l in text.splitlines() if "t2 venice attack" in l]
        assert len(d3_lines) == 1
        assert len(d3_lines[0]) == 160
        assert all(len(l) <= 160 for l in text.splitlines())


def test_summarize_empty(tmp_path):
    db_path = tmp_path / "empty.decisions.db"
    with DecisionLog(db_path) as log:
        text = summarize(log, "empty_game")
        assert text.strip() == "empty_game: no decisions recorded"


def test_main_missing_db(tmp_path, capsys):
    p = tmp_path / "game.toml"
    turn_root = tmp_path / "turns"
    p.write_text(f"""
game_id = "test_game"
turn_root = "{turn_root}"
save_dir = "{tmp_path / 'saves'}"

[seats.venice]
brain = "fake"
persona = "p"
""")
    db_path = turn_root / "test_game.decisions.db"
    assert not db_path.exists()

    rc = main([str(p)])
    assert rc == 0
    assert not db_path.exists()

    captured = capsys.readouterr()
    assert f"no decision log at {db_path}" in captured.out


def test_main_with_existing_db(tmp_path, capsys):
    p = tmp_path / "game.toml"
    turn_root = tmp_path / "turns"
    turn_root.mkdir(parents=True, exist_ok=True)
    p.write_text(f"""
game_id = "test_game"
turn_root = "{turn_root}"
save_dir = "{tmp_path / 'saves'}"

[seats.venice]
brain = "fake"
persona = "p"
""")
    db_path = turn_root / "test_game.decisions.db"
    with DecisionLog(db_path) as log:
        log.record(
            Decision(
                game="test_game",
                turn=1,
                actor="venice",
                kind="attack",
                rung=7,
                situation="sit",
                choice="charge",
            )
        )

    rc = main([str(p)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "test_game: 1 decisions, turns 1..1" in captured.out
    assert "By rung:" in captured.out
    assert "By kind:" in captured.out
    assert "By actor:" in captured.out
    assert "Latest 1:" in captured.out

    # Test with optional --last N
    rc = main([str(p), "--last", "5"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Latest 1:" in captured.out
