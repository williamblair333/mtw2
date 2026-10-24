import asyncio

from parley.discord_bot import format_line, handle_incoming, pump_outbox
from parley.store import Store


class FakeTable:
    def __init__(self, fail_on=None):
        self.sent, self.pairs, self.fail_on = [], [], fail_on

    async def send(self, channel, text):
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("discord down")
        self.sent.append((channel, text))

    async def ensure_pair(self, a, b, humans):
        if (a, b) not in [p[:2] for p in self.pairs]:
            self.pairs.append((a, b, humans))
        return f"<#thread-{a}-{b}>"


NAMES = {"venice": "Doge Enrico", "milan": "Duke Ottone", "england": "player_one (england)"}
HUMANS = {"england": "player_one"}


def run(c):
    return asyncio.run(c)


def test_format_line_trims_and_names():
    line = format_line("Doge Enrico", "Venice", "x" * 3000)
    assert line.startswith("**Doge Enrico (Venice):** ") and len(line) == 2000


def test_pump_posts_in_order_once(tmp_path):
    s = Store(tmp_path / "g.db")
    s.queue("g", 1, "lobby", "venice", "first")
    s.queue("g", 1, "lobby", "milan", "second")
    t = FakeTable()
    assert run(pump_outbox(s, t, "g", NAMES, HUMANS)) == 2
    assert run(pump_outbox(s, t, "g", NAMES, HUMANS)) == 0
    assert [x[1] for x in t.sent] == ["**Doge Enrico (Venice):** first", "**Duke Ottone (Milan):** second"]


def test_pump_survives_send_error(tmp_path):
    s = Store(tmp_path / "g.db")
    s.queue("g", 1, "lobby", "venice", "boom")
    s.queue("g", 1, "lobby", "venice", "after")
    t = FakeTable(fail_on="boom")
    assert run(pump_outbox(s, t, "g", NAMES, HUMANS)) == 0  # stops to keep order
    assert [m.text for m in s.unposted("g")] == ["boom", "after"]
    t.fail_on = None
    assert run(pump_outbox(s, t, "g", NAMES, HUMANS)) == 2


def test_game_channel_name_rules():
    from parley.discord_bot import channel_slug
    assert channel_slug("First Game #2!") == "first-game-2"
    assert channel_slug("army-check") == "army-check"


def test_chronicle_posted_plain(tmp_path):
    s = Store(tmp_path / "g.db")
    s.queue("g", 2, "chronicle", "parley", "Turn 2: all rulers have decided.")
    t = FakeTable()
    run(pump_outbox(s, t, "g", NAMES, HUMANS))
    assert t.sent == [("chronicle", "Turn 2: all rulers have decided.")]


def test_system_notice_in_thread_posted_plain(tmp_path):
    s = Store(tmp_path / "g.db")
    s.queue("g", 2, "pair:england|venice", "parley", "📜 Venice sent England 500 florins.")
    t = FakeTable()
    run(pump_outbox(s, t, "g", NAMES, HUMANS))
    assert t.sent == [("pair:england|venice", "📜 Venice sent England 500 florins.")]


def test_row_that_keeps_failing_is_set_aside(tmp_path):
    from parley.discord_bot import MAX_ATTEMPTS
    s = Store(tmp_path / "g.db")
    s.queue("g", 1, "lobby", "venice", "boom forever")
    s.queue("g", 1, "lobby", "venice", "after")
    t = FakeTable(fail_on="boom")
    attempts = {}
    for _ in range(MAX_ATTEMPTS):
        run(pump_outbox(s, t, "g", NAMES, HUMANS, attempts=attempts))
    assert [x[1] for x in t.sent] == ["**Doge Enrico (Venice):** after"]


def test_bot_lock_refuses_second_instance(tmp_path):
    import pytest
    from parley.discord_bot import acquire_bot_lock
    first = acquire_bot_lock(tmp_path)
    with pytest.raises(RuntimeError, match="already running"):
        acquire_bot_lock(tmp_path)
    first.close()


def test_pair_thread_ensured_with_humans(tmp_path):
    s = Store(tmp_path / "g.db")
    s.queue("g", 1, "pair:england|venice", "venice", "psst")
    s.queue("g", 1, "pair:england|venice", "venice", "again")
    t = FakeTable()
    run(pump_outbox(s, t, "g", NAMES, HUMANS))
    assert t.pairs == [("england", "venice", ["player_one"])]
    assert t.sent[0][0] == "pair:england|venice"


class FakeResponder:
    def __init__(self):
        self.calls = []

    async def on_incoming(self, channel, sender, text):
        self.calls.append((channel, sender, text))
        return []


def test_incoming_from_mapped_human_reaches_responder():
    r = FakeResponder()
    run(handle_incoming(r, HUMANS, "player_one", False, "lobby", "Venice, ally?"))
    assert r.calls == [("lobby", "human:england", "Venice, ally?")]


def test_incoming_from_unmapped_user_ignored():
    r = FakeResponder()
    run(handle_incoming(r, HUMANS, "stranger", False, "lobby", "hi"))
    assert r.calls == []


def test_incoming_from_bot_or_unknown_channel_ignored():
    r = FakeResponder()
    run(handle_incoming(r, HUMANS, "player_one", True, "lobby", "hi"))
    run(handle_incoming(r, HUMANS, "player_one", False, None, "hi"))
    assert r.calls == []


def test_private_command_opens_thread_for_human():
    from parley.discord_bot import private_command
    t = FakeTable()
    seats = {"venice", "milan"}
    reply = run(private_command(t, HUMANS, seats, "player_one", "!private Venice"))
    assert t.pairs == [("england", "venice", ["player_one"])]
    assert "england ↔ venice" in reply and "<#thread-england-venice>" in reply  # clickable link


def test_private_command_rejects_unknown_or_unmapped():
    from parley.discord_bot import private_command
    t = FakeTable()
    assert "unknown faction" in run(private_command(t, HUMANS, {"venice"}, "player_one", "!private atlantis"))
    assert run(private_command(t, HUMANS, {"venice"}, "stranger", "!private venice")) is None
    assert run(private_command(t, HUMANS, {"venice"}, "player_one", "hello venice")) is None
    assert t.pairs == []


def test_incoming_trimmed_to_2000():
    r = FakeResponder()
    run(handle_incoming(r, HUMANS, "player_one", False, "lobby", "y" * 5000))
    assert len(r.calls[0][2]) == 2000
