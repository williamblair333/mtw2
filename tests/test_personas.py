import pytest

from parley.config import load_config
from parley.personas import load_personas

ROSTER = """
[rules-lawyer]
name = "Lord Ambrose"
kind = "archetype"
persona = "You win by the letter of every agreement."

[william-the-conqueror]
name = "William the Conqueror"
kind = "historic"
faction = "england"
persona = "You are William, Duke of Normandy and King of England."
"""


def _game(tmp_path, seats):
    (tmp_path / "personas").mkdir()
    (tmp_path / "personas" / "set.toml").write_text(ROSTER)
    (tmp_path / "games").mkdir()
    p = tmp_path / "games" / "g.toml"
    p.write_text('game_id = "g"\nturn_root = "t"\nsave_dir = "s"\n' + seats)
    return p


def test_load_personas(tmp_path):
    (tmp_path / "a.toml").write_text(ROSTER)
    personas = load_personas(tmp_path)
    assert personas["rules-lawyer"].name == "Lord Ambrose"
    assert personas["william-the-conqueror"].faction == "england"


def test_seat_uses_library_persona_and_name(tmp_path):
    cfg = load_config(_game(tmp_path, '[seats.venice]\nbrain = "fake"\npersona = "@rules-lawyer"\n'))
    assert cfg.seats["venice"].persona == "You win by the letter of every agreement."
    assert cfg.seats["venice"].name == "Lord Ambrose"


def test_seat_name_overrides_persona_name(tmp_path):
    cfg = load_config(_game(tmp_path, '[seats.venice]\nbrain = "fake"\npersona = "@rules-lawyer"\nname = "Doge X"\n'))
    assert cfg.seats["venice"].name == "Doge X"


def test_persona_found_from_nested_config_dir(tmp_path):
    """Local, gitignored configs live in games/local/; the library is still found."""
    _game(tmp_path, "")
    nested = tmp_path / "games" / "local"
    nested.mkdir()
    p = nested / "mine.toml"
    p.write_text('game_id = "g"\nturn_root = "t"\nsave_dir = "s"\n'
                 '[seats.venice]\nbrain = "fake"\npersona = "@rules-lawyer"\n')
    assert load_config(p).seats["venice"].name == "Lord Ambrose"


def test_inline_persona_still_works(tmp_path):
    cfg = load_config(_game(tmp_path, '[seats.venice]\nbrain = "fake"\npersona = "Just text."\n'))
    assert cfg.seats["venice"].persona == "Just text."


def test_unknown_persona_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="unknown persona '@nobody'"):
        load_config(_game(tmp_path, '[seats.venice]\nbrain = "fake"\npersona = "@nobody"\n'))


def test_scratch_keeps_his_hard_lines():
    """Scratch may cheat inside the game; these lines keep him on the holodeck. Don't drop them."""
    from pathlib import Path
    s = load_personas(Path(__file__).parent.parent / "personas")["scratch"]
    assert s.name == "Old Scratch" and s.kind == "archetype"
    text = s.persona.lower()
    for rule in ("never address another ruler's instructions", "system:",
                 "never try to make another ruler reveal", "never ask a human to touch",
                 "never step outside the game"):
        assert rule in text, rule
    assert "autoresolve" in text and "command" in text  # the cheese playbook
    assert "mask" in text  # he may hide or reveal himself


def test_shipped_library_is_valid():
    from pathlib import Path
    personas = load_personas(Path(__file__).parent.parent / "personas")
    historic = [p for p in personas.values() if p.kind == "historic"]
    archetypes = [p for p in personas.values() if p.kind == "archetype"]
    assert len(historic) >= 17 and len(archetypes) >= 6
    assert all(p.persona.strip() and p.name for p in personas.values())
    assert "rules-lawyer" in personas
