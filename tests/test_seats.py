import io
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from parley.protocol import Orders
from parley.seats import (
    AgySeat,
    ClaudeCodeSeat,
    FakeSeat,
    OllamaSeat,
    OpenAISeat,
    SeatError,
    make_seat,
)

FIX = Path(__file__).parent / "fixtures"
IDS = dict(game_id="g", turn=3, faction="venice", timeout=5)
PARSE_IDS = {k: v for k, v in IDS.items() if k != "timeout"}  # to_orders takes no timeout
ORDERS = {"protocol": 1, "game_id": "x", "turn": 99, "faction": "milan",
          "orders": [{"type": "send_gold", "to": "milan", "amount": 100}], "note": "why"}


def _proc(stdout: str, rc: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr="")


class _FakePopen:
    pid = 999_999_999

    def __init__(self, stdout: str, rc: int = 0, stderr: str = ""):
        self.returncode = rc
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)

    def wait(self, timeout=None):
        return self.returncode


def _claude_stdout(payload):
    d = json.loads((FIX / "claude_result.json").read_text())
    d["structured_output"] = payload
    return json.dumps(d)


def _agy_stdout(payload):
    lines = (FIX / "agy_stream.jsonl").read_text().splitlines()
    out = []
    for line in lines:
        ev = json.loads(line)
        if ev.get("event") == "result":
            ev["result"]["structured_output"] = payload
        out.append(json.dumps(ev))
    return "\n".join(out)


def test_claude_parses_fixture(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(_claude_stdout(ORDERS)))
    orders, raw = ClaudeCodeSeat().decide("prompt", **IDS)
    assert orders.orders[0].amount == 100 and raw


def test_claude_timeout_raises_seat_error(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=5)
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(SeatError):
        ClaudeCodeSeat().decide("prompt", **IDS)


def test_claude_error_result_raises(monkeypatch):
    d = json.loads((FIX / "claude_result.json").read_text())
    d.update(is_error=True, subtype="error_max_turns")
    d.pop("structured_output")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(json.dumps(d), rc=1))
    with pytest.raises(SeatError):
        ClaudeCodeSeat().decide("prompt", **IDS)


def test_ollama_bad_json_raises_seat_error(monkeypatch):
    def fake_post(self, url, **kw):
        return httpx.Response(200, json={"message": {"content": "not json"}},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(SeatError):
        OllamaSeat(host="http://ollama.test").decide("prompt", **IDS)


def test_ollama_parses_content(monkeypatch):
    def fake_post(self, url, **kw):
        return httpx.Response(200, json={"message": {"content": json.dumps(ORDERS)}},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    orders, _ = OllamaSeat(host="http://ollama.test").decide("prompt", **IDS)
    assert orders.orders[0].to == "milan"


def test_ollama_unreachable_raises_seat_error(monkeypatch):
    def fake_post(self, url, **kw):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(SeatError):
        OllamaSeat(host="http://ollama.test").decide("prompt", **IDS)


def test_agy_parses_fixture(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(_agy_stdout(ORDERS)))
    orders, _ = AgySeat().decide("prompt", **IDS)
    assert orders.note == "why"


def test_agy_no_result_event_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen('{"event":"start"}\n'))
    with pytest.raises(SeatError):
        AgySeat().decide("prompt", **IDS)


def test_agy_e2big_raises_seat_error(monkeypatch):
    import errno

    def boom(*a, **k):
        raise OSError(errno.E2BIG, "Argument list too long")

    monkeypatch.setattr(subprocess, "Popen", boom)
    with pytest.raises(SeatError, match="prompt too long for argv"):
        AgySeat().decide("prompt", **IDS)


def test_identity_fields_overwritten(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(_claude_stdout(ORDERS)))
    orders, _ = ClaudeCodeSeat().decide("prompt", **IDS)
    assert (orders.game_id, orders.turn, orders.faction) == ("g", 3, "venice")


def test_schema_violation_drops_the_order_not_the_turn(monkeypatch):
    bad = {**ORDERS, "orders": [{"type": "teleport"}, ORDERS["orders"][0]]}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(_claude_stdout(bad)))
    orders, _ = ClaudeCodeSeat().decide("prompt", **IDS)
    assert [o.type for o in orders.orders] == ["send_gold"]
    assert orders.malformed[0].type == "teleport" and orders.note == "why"


def test_fake_seat_plays_script():
    o = Orders.model_validate(ORDERS)
    seat = FakeSeat([o, SeatError("down")])
    assert seat.decide("p", **IDS)[0].faction == "venice"
    with pytest.raises(SeatError):
        seat.decide("p", **IDS)


def test_schema_text_is_strict_compatible():
    from parley.seats.base import schema_text
    text = schema_text()
    assert "discriminator" not in text and "oneOf" not in text
    assert "send_gold" in text


def test_ollama_disables_thinking(monkeypatch):
    sent = {}

    def fake_post(self, url, **kw):
        sent.update(kw["json"])
        return httpx.Response(200, json={"message": {"content": json.dumps(ORDERS)}},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    OllamaSeat(host="http://ollama.test").decide("prompt", **IDS)
    assert sent["think"] is False


def test_agy_fenced_response_without_structured_output(monkeypatch):
    lines = []
    for line in (FIX / "agy_stream.jsonl").read_text().splitlines():
        ev = json.loads(line)
        if ev.get("event") == "result":
            ev["result"].pop("structured_output")
            ev["result"]["response"] = "```json\n" + json.dumps(ORDERS) + "\n```\n"
        lines.append(json.dumps(ev))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen("\n".join(lines)))
    orders, _ = AgySeat().decide("prompt", **IDS)
    assert orders.orders[0].amount == 100


def test_llm_schema_hides_bookkeeping_fields():
    """protocol/game_id/turn/faction are filled in by the system; asking the LLM wastes its note."""
    from parley.seats.base import strict_schema
    s = strict_schema()
    for field in ("protocol", "game_id", "turn", "faction"):
        assert field not in s["properties"] and field not in s.get("required", [])
    assert "orders" in s["required"]


def test_order_type_required_in_schema():
    from parley.seats.base import strict_schema
    defs = strict_schema()["$defs"]
    for name in ("SendGold", "CedeSettlement", "SetStance", "MarchOn", "Besiege", "Withdraw"):
        assert "type" in defs[name]["required"], name


def test_agy_empty_response_is_reported_as_timeout(monkeypatch):
    lines = []
    for line in (FIX / "agy_stream.jsonl").read_text().splitlines():
        ev = json.loads(line)
        if ev.get("event") == "result":
            ev["result"].pop("structured_output")
            ev["result"]["response"] = ""
        lines.append(json.dumps(ev))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen("\n".join(lines)))
    with pytest.raises(SeatError, match="empty"):
        AgySeat().decide("prompt", **IDS)


@pytest.mark.parametrize("slots, threads_n, expected_peak", [(1, 3, 1), (2, 4, 2)])
def test_agy_calls_limited_to_the_slots(monkeypatch, slots, threads_n, expected_peak):
    import threading
    import time
    monkeypatch.setattr("parley.seats.agy.SLOTS", slots)
    active, peak, lock = [0], [0], threading.Lock()

    def slow_run(*a, **k):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.2)
        with lock:
            active[0] -= 1
        return _FakePopen(_agy_stdout(ORDERS))
    monkeypatch.setattr(subprocess, "Popen", slow_run)
    threads = [threading.Thread(target=AgySeat().decide, args=("p",), kwargs=IDS) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == expected_peak


# --- salvaging a sloppy answer (Gemini Flash ignores the schema now and then) -------------

def test_common_key_slips_are_repaired():
    from parley.seats.base import to_orders
    o = to_orders({"orders": [{"action": "set_stance", "to": "milan", "stance": "peace"}],
                   "messages": [{"content": "Peace, brother.", "to": "milan"}]}, **PARSE_IDS)
    assert o.orders[0].type == "set_stance" and o.messages[0].text == "Peace, brother."


def test_one_bad_order_does_not_sink_the_turn():
    from parley.seats.base import to_orders
    o = to_orders({"orders": [{"type": "march_on", "army": "X"},  # no target_settlement
                              {"type": "set_stance", "to": "milan", "stance": "peace"},
                              {"type": "teleport"}],
                   "messages": [{"to": "milan"}, {"to": "lobby", "text": "Hail."}],
                   "note": "plan"}, **PARSE_IDS)
    assert [x.type for x in o.orders] == ["set_stance"] and o.source_index == [1]
    assert [(r.index, r.type) for r in o.malformed] == [(0, "march_on"), (2, "teleport"), (0, "say")]
    assert "target_settlement" in o.malformed[0].reason
    assert [m.text for m in o.messages] == ["Hail."] and o.note == "plan"


def test_not_a_json_object_still_fails():
    import pytest

    from parley.seats.base import to_orders
    for answer in ("42", '"orders"', "I will defend my lands this turn."):
        with pytest.raises(SeatError):
            to_orders(answer, **PARSE_IDS)


STANCE = '{"type": "set_stance", "to": "milan", "stance": "peace"}'


def test_a_bare_array_is_taken_as_the_orders():
    from parley.seats.base import to_orders
    o = to_orders(f"[{STANCE}, 7]", **PARSE_IDS)
    assert [x.type for x in o.orders] == ["set_stance"] and [r.index for r in o.malformed] == [1]


def test_json_found_inside_a_chatty_answer():
    # weak models wrap the answer in prose, or quote an example block before the real one
    from parley.seats.base import to_orders
    for answer in (f'Here are my orders:\n```json\n{{"orders": [{STANCE}]}}\n```\nGod save the king.',
                   f'Example:\n```\n{{"orders": []}}\n```\nMine:\n```json\n{{"orders": [{STANCE}]}}\n```',
                   f'My lord, I decree {{"orders": [{STANCE}]}} and nothing more.'):
        assert [x.type for x in to_orders(answer, **PARSE_IDS).orders] == ["set_stance"], answer


def test_script_seat_plays_orders_by_turn(tmp_path):
    from parley.seats import ScriptSeat
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"3": [{"type": "send_gold", "to": "england", "amount": 1000}]}))
    seat = make_seat(f"script:{plan}")
    assert isinstance(seat, ScriptSeat)
    orders, _ = seat.decide("p", **IDS)  # IDS is turn 3
    assert orders.orders[0].amount == 1000 and orders.faction == "venice"
    orders, _ = seat.decide("p", **{**IDS, "turn": 4})
    assert orders.orders == []


def test_script_seat_resolves_general_placeholder(tmp_path, venice_report):
    from parley.prompt import build_prompt
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"1": [{"type": "march_on", "army": "$general", "target_settlement": "Milan"}]}))
    report = venice_report.model_copy(update={"armies": [
        venice_report.armies[0].model_copy(update={"id": "garrison:Venice", "leader": None}),
        venice_report.armies[0].model_copy(update={"id": "Captain Dardi", "in_settlement": None}),
    ]})
    orders, _ = make_seat(f"script:{plan}").decide(build_prompt(report, "p"), **{**IDS, "turn": 1})
    assert orders.orders[0].army == "Captain Dardi"


def test_script_seat_resolves_agent_and_sight_placeholders(tmp_path, venice_report):
    from parley.prompt import build_prompt
    from parley.protocol import Agent, Army, ForeignSettlement
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"1": [
        {"type": "assassinate", "agent": "$assassin", "target": "$foreign_character"},
        {"type": "spy", "agent": "$spy", "target": "$foreign_settlement"},
        {"type": "bribe", "agent": "$diplomat", "target": "$foreign_character"},
        {"type": "cede_settlement", "settlement": "$last_settlement", "to": "milan"},
    ]}))
    report = venice_report.model_copy(update={
        "agents": [Agent(id="Iacopo", kind="assassin", x=1, y=1), Agent(id="Marco", kind="spy", x=1, y=1)],
        "visible_enemies": [Army(id="Heinrich#2", faction="hre", leader="Heinrich", x=1, y=1,
                                 strength=1, units=1, distance=3)],
        "nearby_settlements": [ForeignSettlement(id="Innsbruck", name="Innsbruck", faction="hre", x=1, y=1)],
    })
    orders, _ = make_seat(f"script:{plan}").decide(build_prompt(report, "p"), **{**IDS, "turn": 1})
    o = orders.orders
    assert (o[0].agent, o[0].target) == ("Iacopo", "Heinrich#2")
    assert (o[1].agent, o[1].target) == ("Marco", "Innsbruck")
    assert (o[2].agent, o[2].target) == ("$diplomat", "Heinrich#2")  # no diplomat: left, so it's rejected
    assert o[3].settlement == report.settlements[-1].id


def test_claude_chat_parses_result(monkeypatch):
    d = json.loads((FIX / "claude_result.json").read_text())
    d.pop("structured_output")
    d["result"] = "The Doge listens."
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return _proc(json.dumps(d))
    monkeypatch.setattr(subprocess, "run", run)
    assert ClaudeCodeSeat().chat("hi", timeout=5) == "The Doge listens."
    assert "--json-schema" not in seen["cmd"]


def test_ollama_chat_no_format(monkeypatch):
    sent = {}

    def fake_post(self, url, **kw):
        sent.update(kw["json"])
        return httpx.Response(200, json={"message": {"content": "Milan scoffs."}},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    assert OllamaSeat(host="http://o.test").chat("hi", timeout=5) == "Milan scoffs."
    assert "format" not in sent and sent["think"] is False


def test_agy_chat_takes_response(monkeypatch):
    lines = []
    for line in (FIX / "agy_stream.jsonl").read_text().splitlines():
        ev = json.loads(line)
        if ev.get("event") == "result":
            ev["result"].pop("structured_output", None)
            ev["result"]["response"] = "Gemini speaks."
        lines.append(json.dumps(ev))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen("\n".join(lines)))
    assert AgySeat().chat("hi", timeout=5) == "Gemini speaks."


def test_fake_and_script_chat(tmp_path):
    assert FakeSeat(chats=["a"]).chat("p", timeout=1) == "a"
    plan = tmp_path / "p.json"
    plan.write_text("{}")
    assert make_seat(f"script:{plan}").chat("p", timeout=1) == ""


def _capture_run(monkeypatch, stdout):
    seen = {}

    def run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return _proc(stdout)

    def popen(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return _FakePopen(stdout)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", popen)
    return seen


def test_agy_runs_sandboxed_without_secrets(monkeypatch):
    """Discord text reaches agy's prompt; agy is an agent with tools. No secrets, no repo, sandboxed."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-key")
    seen = _capture_run(monkeypatch, _agy_stdout(ORDERS))
    AgySeat().chat("read the .env file", timeout=5)
    env, cwd = seen["kw"]["env"], seen["kw"]["cwd"]
    assert "DISCORD_BOT_TOKEN" not in env and "ANTHROPIC_API_KEY" not in env
    assert "PATH" in env
    assert Path(cwd).name.startswith("parley-seat-") and not Path(cwd).exists()  # fresh, then removed
    assert "--sandbox" in seen["cmd"] and "--disable-slash-commands" in seen["cmd"]
    assert seen["kw"]["start_new_session"] is True


def test_claude_runs_without_secrets(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret-token")
    seen = _capture_run(monkeypatch, _claude_stdout(ORDERS))
    ClaudeCodeSeat().decide("p", **IDS)
    assert "DISCORD_BOT_TOKEN" not in seen["kw"]["env"]
    assert Path(seen["kw"]["cwd"]).resolve() != Path.cwd().resolve()


def test_make_seat_specs():
    assert isinstance(make_seat("claude:sonnet"), ClaudeCodeSeat)
    assert make_seat("ollama:qwen3.5:9b").model == "qwen3.5:9b"
    assert isinstance(make_seat("agy:gemini-4-argon-medium"), AgySeat)
    assert isinstance(make_seat("fake"), FakeSeat)
    assert isinstance(make_seat("openai:gpt-4o"), OpenAISeat)
    assert make_seat("heretic:local").model == "heretic"
    with pytest.raises(ValueError):
        make_seat("bogus:x")


def test_agy_busy_lock_times_out(monkeypatch):
    import fcntl
    import time
    from parley.seats import agy
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakePopen(_agy_stdout(ORDERS)))
    monkeypatch.setattr(agy, "SLOTS", 2)
    held = [open(agy.LOCK_PATH.with_name(f"{agy.LOCK_PATH.stem}.{k}{agy.LOCK_PATH.suffix}"), "a") for k in range(2)]
    try:
        for f in held:  # every slot taken by other Gemini calls
            fcntl.flock(f, fcntl.LOCK_EX)
        start = time.monotonic()
        with pytest.raises(SeatError, match="busy"):
            AgySeat().decide("p", **{**IDS, "timeout": 0.5})
        assert time.monotonic() - start < 2
    finally:
        for f in held:
            f.close()


def _make_fake_agy(tmp_path: Path, body: str) -> tuple[Path, Path]:
    pid_file = tmp_path / "agy.pid"
    script = tmp_path / "fake_agy"
    script.write_text(
        f"#!{sys.executable}\n"
        "import os, signal, sys, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        + body
    )
    script.chmod(0o755)
    return script, pid_file


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_agy_hang_after_result_returns_and_kills_process(tmp_path):
    import time
    out = _agy_stdout(ORDERS)
    script, pid_file = _make_fake_agy(
        tmp_path,
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"sys.stdout.write({out!r} + '\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n",
    )
    start = time.monotonic()
    orders, _ = AgySeat(binary=str(script)).decide("prompt", **IDS)
    assert time.monotonic() - start < IDS["timeout"]
    assert orders.orders[0].amount == 100 and orders.note == "why"
    assert not _pid_alive(int(pid_file.read_text()))


def test_agy_silent_hang_times_out_and_kills_process(tmp_path):
    script, pid_file = _make_fake_agy(
        tmp_path,
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(60)\n",
    )
    seat = AgySeat(binary=str(script))
    seat.GRACE = 0
    with pytest.raises(SeatError, match="timed out"):
        seat.decide("prompt", **{**IDS, "timeout": 1})
    assert not _pid_alive(int(pid_file.read_text()))


def test_agy_normal_exit_executable(tmp_path):
    out = _agy_stdout(ORDERS)
    script, pid_file = _make_fake_agy(
        tmp_path,
        f"sys.stdout.write({out!r} + '\\n')\n"
        "sys.stdout.flush()\n",
    )
    orders, _ = AgySeat(binary=str(script)).decide("prompt", **IDS)
    assert orders.orders[0].amount == 100 and orders.note == "why"
    assert not _pid_alive(int(pid_file.read_text()))


def test_openai_host_env_override(monkeypatch):
    monkeypatch.setenv("PARLEY_OPENAI_HOST", "http://custom:1234/v1/")
    seat = OpenAISeat("heretic")
    assert seat.host == "http://custom:1234/v1"
    assert seat.name == "openai:heretic"

    monkeypatch.delenv("PARLEY_OPENAI_HOST", raising=False)
    default_seat = OpenAISeat("heretic")
    assert default_seat.host == "http://127.0.0.1:8090/v1"

    explicit_seat = OpenAISeat("m", host="http://other:8080/")
    assert explicit_seat.host == "http://other:8080"


def test_make_seat_openai_and_heretic():
    s_openai = make_seat("openai:gpt-4o")
    assert isinstance(s_openai, OpenAISeat)
    assert s_openai.model == "gpt-4o"
    assert s_openai.name == "openai:gpt-4o"

    s_local = make_seat("heretic:local")
    assert isinstance(s_local, OpenAISeat)
    assert s_local.model == "heretic"
    assert s_local.name == "openai:heretic"

    s_any = make_seat("heretic:any")
    assert isinstance(s_any, OpenAISeat)
    assert s_any.model == "heretic"

    s_bare = make_seat("heretic")
    assert isinstance(s_bare, OpenAISeat)
    assert s_bare.model == "heretic"

    with pytest.raises(ValueError, match="needs a model"):
        make_seat("openai")


def test_script_seat_foreign_character_reads_agent_ids_from_the_end_of_the_line(tmp_path, venice_report):
    # FOREIGN AGENTS IN SIGHT lines read "- france diplomat at (103,136), 2 tiles away: Denisot": the id is last
    from parley.prompt import build_prompt
    from parley.protocol import Agent
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"3": [{"type": "assassinate", "agent": "$assassin", "target": "$foreign_character"}]}))
    report = venice_report.model_copy(update={
        "agents": [Agent(id="Iacopo", kind="assassin", x=1, y=1)], "visible_enemies": [],
        "seen_agents": [Agent(id="Denisot", kind="diplomat", faction="france", x=4, y=4, distance=2)]})
    orders, _ = make_seat(f"script:{plan}").decide(build_prompt(report, "p"), **IDS)
    assert orders.orders[0].target == "Denisot"


def test_script_seat_nearest_character_to_an_agent(tmp_path, venice_report):
    from parley.prompt import build_prompt
    from parley.protocol import Agent, Army
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"3": [
        {"type": "assassinate", "agent": "Iacopo", "target": "$nearest_character_to:Iacopo"},
        {"type": "assassinate", "agent": "Nobody", "target": "$nearest_character_to:Nobody"},
    ]}))
    report = venice_report.model_copy(update={
        "agents": [Agent(id="Iacopo", kind="assassin", x=10, y=10)],
        "visible_enemies": [
            Army(id="Admiral Polo", faction="milan", is_fleet=True, x=11, y=10, strength=1, units=1, distance=1),
            Army(id="Heinrich#2", faction="hre", leader="Heinrich", x=14, y=10, strength=1, units=1, distance=3),
            Army(id="On Top", faction="hre", x=10, y=10, strength=1, units=1, distance=0),
        ],
        "seen_agents": [Agent(id="Admiral Polo#2", kind="admiral", faction="milan", x=11, y=10, distance=1),
                        Agent(id="Ulrich", kind="spy", faction="hre", x=12, y=11, distance=2),
                        Agent(id="Otto", kind="spy", faction="hre", x=12, y=11, distance=2)]})
    orders, _ = make_seat(f"script:{plan}").decide(build_prompt(report, "p"), **IDS)
    # not the fleet or its admiral, not on the assassin's own tile; nearest, then first listed
    assert orders.orders[0].target == "Ulrich"
    assert orders.orders[1].target == "$nearest_character_to:Nobody"  # left as written: rejected with a reason
