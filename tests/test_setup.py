import random
import tomllib
from pathlib import Path

import pytest

from parley.config import load_config
from parley.setup import SetupError, build_game, write_game

ROOT = Path(__file__).parent.parent
TEMPLATE = tomllib.loads((ROOT / "games" / "template.toml").read_text())


def _build(**kw):
    kw.setdefault("rng", random.Random(1))
    return build_game(TEMPLATE, "g3", personas_dir=ROOT / "personas", **kw)


def rivals(game):
    return sorted(game["seats"])


def test_template_lists_every_playable_faction():
    assert len(TEMPLATE["factions"]) == 18 and "england" in TEMPLATE["factions"]


def test_play_list_exactly():
    game, hidden = _build(play=["france", "hre", "venice"])
    assert rivals(game) == ["france", "hre", "venice"] and hidden == {}
    assert game["game_id"] == "g3"


def test_play_random_n_excludes_humans():
    game, _ = _build(play="random 6")
    assert len(game["seats"]) == 6 and "england" not in game["seats"]


def test_random_differs_by_seed():
    a, _ = _build(play="random 6", rng=random.Random(1))
    b, _ = _build(play="random 6", rng=random.Random(2))
    assert rivals(a) != rivals(b)


def test_play_all_is_every_non_human():
    game, _ = _build(play="all")
    assert len(game["seats"]) == 17


def test_play_from_template_when_not_given():
    game, _ = _build()
    assert len(game["seats"]) == int(TEMPLATE["play"].split()[1])  # template default "random N"


def test_personas_historic_uses_each_factions_ruler():
    game, _ = _build(play=["france", "scotland"], personas="historic")
    assert game["seats"]["france"]["persona"] == "@philip-i-of-france"
    assert game["seats"]["scotland"]["persona"] == "@malcolm-canmore"


def test_personas_archetypes_are_distinct_and_never_scratch():
    game, _ = _build(play=["france", "hre", "venice", "sicily"], personas="archetypes")
    ps = [s["persona"] for s in game["seats"].values()]
    assert len(set(ps)) == 4 and "@scratch" not in ps


def test_secret_scratch_hidden_behind_a_mask():
    game, hidden = _build(play=["france", "hre", "venice"], scratch=True)
    [(faction, real)] = hidden["seats"].items()
    assert real["persona"] == "@scratch" and real["brain"] == "claude:opus"
    plain, _ = _build(play=["france", "hre", "venice"])
    # the game file looks exactly as it would without the secret: nothing marks the seat
    assert game["seats"] == plain["seats"]
    assert real["name"]  # he signs with the ruler's normal name
    assert "scratch" not in str(game).lower()


def test_summary_does_not_give_the_secret_away():
    from parley.setup import summary
    game, hidden = _build(play=["france", "hre", "venice"], scratch=True)
    plain, _ = _build(play=["france", "hre", "venice"])
    assert summary(game, hidden).splitlines()[1:4] == summary(plain, {}).splitlines()[1:4]


def test_seat_override_persona_and_brain():
    game, _ = _build(play=["france"], seats=["france=@rules-lawyer:opus", "venice=@zealot"])
    assert game["seats"]["france"] == {**game["seats"]["france"], "persona": "@rules-lawyer",
                                       "brain": "claude:opus"}
    assert game["seats"]["venice"]["persona"] == "@zealot"  # an override adds the faction


def test_brain_override_for_all():
    game, _ = _build(play=["france", "hre"], brain="flash")
    assert {s["brain"] for s in game["seats"].values()} == {"agy:gemini-3.8-flash-low"}


@pytest.mark.parametrize("kw,msg", [
    (dict(play=["atlantis"]), "unknown faction"),
    (dict(play=["england"]), "is a human"),
    (dict(play="random 40"), "only 17"),
    (dict(play="sometimes"), "play must be"),
    (dict(personas="vibes"), "personas must be"),
    (dict(seats=["france"]), "faction=@persona"),
])
def test_setup_errors(kw, msg):
    with pytest.raises(SetupError, match=msg):
        _build(**kw)


def test_written_game_loads_and_resolves_hidden(tmp_path):
    (tmp_path / "personas").symlink_to(ROOT / "personas")
    games = tmp_path / "games"
    games.mkdir()
    game, hidden = _build(play=["france", "hre"], scratch=True)
    path = write_game(game, hidden, games / "g3.toml")
    cfg = load_config(path)
    faction = next(iter(hidden["seats"]))
    assert cfg.seats[faction].brain == "claude:opus"
    assert "Old Scratch" in cfg.seats[faction].persona or "holodeck" in cfg.seats[faction].persona.lower()
    assert cfg.seats[faction].name != "Old Scratch"  # still masked
    assert (games / "g3.hidden.toml").exists()


def _cli(tmp_path, *args):
    from parley.__main__ import main
    out = tmp_path / "local"
    return main(["new-game", *args, "--template", str(ROOT / "games" / "template.toml"),
                 "--dir", str(out)]), out


def test_cli_new_game_writes_a_loadable_game(tmp_path, capsys):
    rc, out = _cli(tmp_path, "g9", "--rivals", "3", "--personas", "historic")
    assert rc == 0
    cfg_text = (out / "g9.toml").read_text()
    assert 'game_id = "g9"' in cfg_text and cfg_text.count("[seats.") == 3
    assert "3 LLM rivals" in capsys.readouterr().out


def test_cli_refuses_existing_game(tmp_path, capsys):
    _cli(tmp_path, "g9", "--rivals", "1")
    rc, _ = _cli(tmp_path, "g9", "--rivals", "1")
    assert rc != 0 and "already exists" in capsys.readouterr().err


def test_cli_from_existing_game_keeps_seats(tmp_path):
    _cli(tmp_path, "g1", "--play", "france", "hre", "--scratch")
    from parley.__main__ import main
    rc = main(["new-game", "g2", "--from", "g1", "--dir", str(tmp_path / "local")])
    assert rc == 0
    g2 = (tmp_path / "local" / "g2.toml").read_text()
    assert 'game_id = "g2"' in g2 and "[seats.france]" in g2 and "[seats.hre]" in g2
    assert (tmp_path / "local" / "g2.hidden.toml").exists()


def test_cli_ask(tmp_path, monkeypatch):
    answers = iter(["france hre", "archetypes", "flash", "n"])
    monkeypatch.setattr("builtins.input", lambda _="": next(answers))
    rc, out = _cli(tmp_path, "g5", "--ask")
    text = (out / "g5.toml").read_text()
    assert rc == 0 and "[seats.france]" in text and "agy:gemini-3.8-flash-low" in text


def test_cli_help_shows_examples(capsys):
    from parley.__main__ import main
    with pytest.raises(SystemExit):
        main(["new-game", "--help"])
    assert "--seat france=@rules-lawyer:opus" in capsys.readouterr().out


def test_help_has_copious_examples():
    from parley.setup import HELP_EXAMPLES
    for snippet in ("--rivals 6", "--personas archetypes", "--scratch", "--seat france=@rules-lawyer:opus",
                    "--play all", "--ask", "--brain flash", "--autoplay --until 30"):
        assert snippet in HELP_EXAMPLES, snippet


def test_cli_autoplay_game_has_no_humans(tmp_path):
    import tomllib

    from parley.config import AutoplayConfig
    rc, out = _cli(tmp_path, "soak", "--play", "france", "hre", "--autoplay", "--until", "30", "--wait", "120",
                   "--seat", "venice=@rules-lawyer:script:games/soak-test.json")
    assert rc == 0
    game = tomllib.loads((out / "soak.toml").read_text())
    auto = AutoplayConfig(**game["autoplay"])
    assert (auto.until_turn, auto.wait) == (30, 120)
    assert game.get("humans", {}) == {} and game["seats"]["venice"]["brain"] == "script:games/soak-test.json"


def test_control_and_adviser_options():
    from parley.setup import build_game
    template = {"factions": {"england": {}, "france": {}, "hre": {}}, "humans": {"england": "ann"}}
    game, _ = build_game(template, "obs", personas_dir=ROOT / "personas", play="all", autoplay={},
                         control=["england=full", "france=diplomacy,armies"], adviser=["england"])
    assert game["seats"]["england"]["control"] == "full" and game["seats"]["england"]["adviser"] == "ann"
    assert game["seats"]["france"]["control"] == ["diplomacy", "armies"]
    assert "control" not in game["seats"]["hre"]


def test_control_option_errors():
    import pytest

    from parley.setup import SetupError, build_game
    template = {"factions": {"england": {}}}
    with pytest.raises(SetupError, match="unknown control area"):
        build_game(template, "x", personas_dir=ROOT / "personas", play="all", control=["england=navy"])
    with pytest.raises(SetupError, match="not seated"):
        build_game(template, "x", personas_dir=ROOT / "personas", play="all", control=["spain=full"])
    with pytest.raises(SetupError, match="--adviser"):
        build_game(template, "x", personas_dir=ROOT / "personas", play="all", adviser=["england"])


def test_autoplay_all_includes_the_templates_human_faction():
    from parley.setup import build_game
    template = {"factions": {"england": {}, "france": {}}, "humans": {"england": "ann"}}
    game, _ = build_game(template, "soak", personas_dir=ROOT / "personas", play="all", autoplay={})
    assert sorted(game["seats"]) == ["england", "france"]
