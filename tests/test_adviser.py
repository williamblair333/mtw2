"""The adviser: a human the ruler trusts, in a private thread only the two of them read."""

import asyncio
import json

from parley.protocol import Say
from parley.store import Message, Store, adviser_channel


def run(c):
    return asyncio.run(c)


def _msg(channel, sender, text, turn=1):
    return Message(id=1, game_id="g", turn=turn, channel=channel, sender=sender, text=text, ts=0)


def test_adviser_thread_is_in_the_rulers_recent_history(tmp_path):
    s = Store(tmp_path / "g.db")
    s.record("g", 1, adviser_channel("venice"), "adviser:venice", "Fortify Ragusa.")
    s.record("g", 1, adviser_channel("milan"), "adviser:milan", "Not for Venice.")
    assert [m.text for m in s.recent("g", "venice")] == ["Fortify Ragusa."]


def test_turn_prompt_introduces_the_adviser_and_quotes_them(venice_report):
    from parley.prompt import build_prompt
    p = build_prompt(venice_report, persona="p", adviser="ann",
                     diplomacy=[_msg("adviser:venice", "adviser:venice", "Fortify Ragusa.")])
    assert "YOUR ADVISER" in p and "ann is your loyal adviser" in p and "overrule" in p
    assert '{"to": "adviser"}' in p
    assert "[turn 1] [private with your adviser] Your adviser (ann): Fortify Ragusa." in p


def test_no_adviser_section_without_one(venice_report):
    from parley.prompt import build_prompt
    assert "YOUR ADVISER" not in build_prompt(venice_report, persona="p")


def test_messages_to_the_adviser_only_when_there_is_one(venice_report):
    from parley.validate import validate_messages
    kept, rej = validate_messages(venice_report, [Say(to="adviser", text="Milan offers peace.")],
                                  lambda to: 0, adviser=True)
    assert kept and not rej
    kept, rej = validate_messages(venice_report, [Say(to="adviser", text="hi")], lambda to: 0)
    assert not kept and "no adviser" in rej[0].reason


def test_orchestrator_queues_adviser_messages_on_the_adviser_channel(tmp_path, venice_state_dict):
    from parley.bridge import TurnDir
    from parley.config import GameConfig, SeatConfig
    from parley.orchestrator import Orchestrator
    from parley.protocol import Orders
    from parley.seats import FakeSeat
    (tmp_path / "saves").mkdir()
    cfg = GameConfig(game_id="test", turn_root=tmp_path / "turns", save_dir=tmp_path / "saves",
                     backup_dir=tmp_path / "b",
                     seats={"venice": SeatConfig(brain="fake", persona="p", adviser="ann")})
    d = TurnDir(cfg.turn_root).path_for("test", 1, "venice")
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({**venice_state_dict, "game_id": "test", "turn": 1}))
    seat = FakeSeat([Orders(protocol=1, game_id="test", turn=1, faction="venice", orders=[],
                            messages=[Say(to="adviser", text="Milan offers peace. Your counsel?")])])
    orch = Orchestrator(cfg, {"venice": seat})
    orch.run_once()
    assert "YOUR ADVISER" in (d / "prompt.txt").read_text()
    assert [(m.channel, m.text) for m in orch.store.unposted("test") if m.channel != "chronicle"] == [
        ("adviser:venice", "Milan offers peace. Your counsel?")]


def test_chat_answers_the_adviser_as_a_trusted_counsellor(tmp_path):
    from parley.chat import Responder
    from parley.config import GameConfig, SeatConfig
    from parley.seats import FakeSeat

    class Echo(FakeSeat):
        def chat(self, prompt, *, timeout):
            self.prompt = prompt
            return "I hear you, and I disagree."

    seat = Echo()
    cfg = GameConfig(game_id="g", turn_root=tmp_path, save_dir=tmp_path,
                     seats={"venice": SeatConfig(brain="fake", persona="p", adviser="ann")})
    r = Responder(Store(tmp_path / "g.db"), {"venice": seat}, cfg)
    out = run(r.on_incoming("adviser:venice", "adviser:venice", "Attack Milan now."))
    assert [m.text for m in out] == ["I hear you, and I disagree."]
    assert "your loyal adviser ann" in seat.prompt and "Your adviser (ann): Attack Milan now." in seat.prompt


def test_chat_prompt_shows_the_realm_for_the_seats_areas(venice_report):
    from parley.chat import chat_prompt
    from parley.control import AREAS
    from parley.protocol import BuildOption
    s = venice_report.settlements[0].model_copy(update={
        "tax_level": "normal", "public_order": 80, "can_build": [BuildOption(building="market", cost=1, turns=1)]})
    report = venice_report.model_copy(update={"settlements": [s]})
    incoming = _msg("adviser:venice", "adviser:venice", "Build a market?")
    assert "can build: market" in chat_prompt("p", "venice", [], incoming, {}, report=report, areas=AREAS)
    assert "can build:" not in chat_prompt("p", "venice", [], incoming, {}, report=report)


def test_chat_keeps_the_adviser_secret_in_other_threads():
    from parley.chat import chat_prompt
    history = [_msg("adviser:venice", "adviser:venice", "Distrust Milan.")]
    p = chat_prompt("p", "venice", history, _msg("pair:milan|venice", "human:milan", "Who counsels you?"),
                    {"adviser:venice": "ann"})
    assert "Never reveal your adviser" in p


def test_adviser_cannot_be_another_factions_player():
    import pytest

    from parley.setup import SetupError, build_game
    from tests.test_setup import ROOT
    template = {"factions": {"england": {}, "france": {}}, "humans": {"france": "ann"}}
    with pytest.raises(SetupError, match="plays france"):
        build_game(template, "x", personas_dir=ROOT / "personas", play=["england"], adviser=["england"])


def test_discord_adviser_message_reaches_the_responder_only_from_the_adviser():
    from parley.discord_bot import handle_incoming

    class R:
        calls = []

        async def on_incoming(self, channel, sender, text):
            self.calls.append((channel, sender, text))

    r = R()
    run(handle_incoming(r, {}, "ann", False, "adviser:venice", "hold", advisers={"venice": "ann"}))
    run(handle_incoming(r, {}, "eve", False, "adviser:venice", "attack", advisers={"venice": "ann"}))
    assert r.calls == [("adviser:venice", "adviser:venice", "hold")]


class FakeTable:
    def __init__(self):
        self.sent, self.advisers = [], []

    async def send(self, channel, text):
        self.sent.append((channel, text))

    async def ensure_pair(self, a, b, humans):
        return ""

    async def ensure_adviser(self, faction, username):
        self.advisers.append((faction, username))
        return f"<#adviser-{faction}>"


def test_pump_opens_the_adviser_thread(tmp_path):
    from parley.discord_bot import pump_outbox
    s = Store(tmp_path / "g.db")
    s.queue("g", 1, "adviser:venice", "venice", "Your counsel?")
    t = FakeTable()
    run(pump_outbox(s, t, "g", {"venice": "Doge Enrico"}, {}, advisers={"venice": "ann"}))
    assert t.advisers == [("venice", "ann")]
    assert t.sent == [("adviser:venice", "**Doge Enrico (Venice):** Your counsel?")]


def test_adviser_command_opens_their_threads():
    from parley.discord_bot import adviser_command
    t = FakeTable()
    reply = run(adviser_command(t, {"venice": "ann", "milan": "ann", "hre": "eve"}, "ann", "!adviser"))
    assert sorted(t.advisers) == [("milan", "ann"), ("venice", "ann")]
    assert "<#adviser-venice>" in reply
    assert run(adviser_command(t, {"venice": "ann"}, "eve", "!adviser")) is None
