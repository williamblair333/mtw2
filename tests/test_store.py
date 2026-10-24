from parley.store import Store, pair_channel


def test_pair_channel_sorted():
    assert pair_channel("venice", "england") == "pair:england|venice"
    assert pair_channel("england", "venice") == "pair:england|venice"


def test_recent_scopes_to_faction(tmp_path):
    s = Store(tmp_path / "g.db")
    s.record("g", 1, "lobby", "venice", "hello all")
    s.record("g", 1, "pair:england|venice", "human:england", "psst venice")
    s.record("g", 1, "pair:hre|milan", "milan", "secret")
    assert [m.text for m in s.recent("g", "venice")] == ["hello all", "psst venice"]


def test_underscore_ids_match_exactly(tmp_path):
    s = Store(tmp_path / "g.db")
    s.record("g", 1, "pair:papalXstates|venice", "venice", "not for the pope")
    assert s.recent("g", "papal_states") == []


def test_recent_other_game_excluded(tmp_path):
    s = Store(tmp_path / "g.db")
    s.record("other", 1, "lobby", "venice", "old game")
    assert s.recent("g", "venice") == []


def test_outbox_posts_once(tmp_path):
    s = Store(tmp_path / "g.db")
    a = s.queue("g", 3, "lobby", "venice", "first")
    s.queue("g", 3, "lobby", "venice", "second")
    assert [m.text for m in s.unposted("g")] == ["first", "second"]
    s.mark_posted(a)
    assert [m.text for m in s.unposted("g")] == ["second"]
    assert [m.text for m in s.recent("g", "venice")] == ["first"]


def test_sent_count(tmp_path):
    s = Store(tmp_path / "g.db")
    s.queue("g", 3, "lobby", "venice", "a")
    s.queue("g", 3, "lobby", "venice", "b")
    assert s.sent_count("g", 3, "venice", "lobby") == 2
    assert s.sent_count("g", 4, "venice", "lobby") == 0
    assert s.sent_count("g", 3, "venice", "pair:milan|venice") == 0


def test_chat_replies_dont_use_turn_cap(tmp_path):
    s = Store(tmp_path / "g.db")
    for _ in range(3):
        s.queue("g", 3, "pair:england|venice", "venice", "chat", kind="chat")
    assert s.sent_count("g", 3, "venice", "pair:england|venice") == 0
    assert s.chat_count("g", 3, "venice") == 3


def test_failed_rows_set_aside(tmp_path):
    s = Store(tmp_path / "g.db")
    a = s.queue("g", 1, "pair:england|venice", "venice", "stuck")
    s.queue("g", 1, "lobby", "venice", "next")
    s.mark_failed(a)
    assert [m.text for m in s.unposted("g")] == ["next"]


def test_old_database_gains_kind_column(tmp_path):
    import sqlite3
    db = sqlite3.connect(tmp_path / "g.db")
    db.executescript("CREATE TABLE outbox (id INTEGER PRIMARY KEY, game_id TEXT, turn INTEGER, "
                     "channel TEXT, sender TEXT, text TEXT, ts REAL, posted INTEGER DEFAULT 0);")
    db.execute("INSERT INTO outbox (game_id, turn, channel, sender, text, ts) VALUES ('g',1,'lobby','venice','old',0)")
    db.commit()
    db.close()
    s = Store(tmp_path / "g.db")
    assert s.sent_count("g", 1, "venice", "lobby") == 1  # old rows count as turn messages


def test_survives_reopen(tmp_path):
    Store(tmp_path / "g.db").record("g", 1, "lobby", "venice", "kept")
    assert Store(tmp_path / "g.db").recent("g", "venice")[0].text == "kept"


def test_recent_limit_keeps_newest(tmp_path):
    s = Store(tmp_path / "g.db")
    for i in range(5):
        s.record("g", 1, "lobby", "venice", f"m{i}")
    assert [m.text for m in s.recent("g", "venice", limit=2)] == ["m3", "m4"]
