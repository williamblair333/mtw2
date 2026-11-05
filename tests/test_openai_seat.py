"""The streamed OpenAI-compatible seat (Heretic on llama-server) against a fake server whose
clock moves as it streams: STANDARDS `ruler-budget` (run9 lost 4 of 46 turns to 5-8k-token
answers, ~85% thinking, past seat_timeout = 420)."""

import json
import tomllib

import httpx
import pytest

from parley.config import GameConfig
from parley.protocol import Orders
from parley.seats import OpenAISeat, RulerBudget, SeatError, make_seat
from parley.seats.base import salvage_json, strict_schema

IDS = dict(game_id="g", turn=3, faction="venice")
ORDERS = {"orders": [{"type": "send_gold", "to": "milan", "amount": 100},
                     {"type": "send_gold", "to": "genoa", "amount": 50},
                     {"type": "send_gold", "to": "pisa", "amount": 25}], "note": "why"}
TEXT = json.dumps(ORDERS)


def _sse(delta: dict | None = None, finish: str | None = None, choices=True) -> bytes:
    chunk = {"choices": [{"delta": delta or {}, "finish_reason": finish}]} if choices else {"choices": []}
    return f"data: {json.dumps(chunk)}\n\n".encode()


class FakeLlama:
    """A llama-server stand-in: each POST takes the next answer; every streamed chunk moves the
    seat's clock on by `step` seconds (the server's generation speed)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.bodies: list[dict] = []
        self.headers: list[httpx.Headers] = []
        self.urls: list[str] = []
        self.gets = 0
        self.now = 0.0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            self.gets += 1
            assert str(request.url) == "http://127.0.0.1:8090/health"
            return httpx.Response(200)
        self.bodies.append(json.loads(request.content))
        self.headers.append(request.headers)
        self.urls.append(str(request.url))
        answer = self.answers.pop(0)
        if answer == "drop":
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        if isinstance(answer, int):
            return httpx.Response(answer)
        if "json" in answer:  # a server that ignored stream
            return httpx.Response(200, json=answer["json"])
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=self._stream(answer))

    def _stream(self, a: dict):
        step = a.get("step", 0.0)
        self.now += a.get("prompt_s", 0.0)
        for r in a.get("reasoning", []):
            self.now += step
            yield _sse({"reasoning_content": r})
        for c in a.get("content", []):
            self.now += step
            yield _sse({"content": c})
        if "raw" in a:
            yield a["raw"]
        if "raise" in a:  # the read timed out (the server stalled) or the connection dropped
            raise a["raise"]
        yield _sse(finish=a.get("finish", "stop"))
        yield b"data: [DONE]\n\n"

    def seat(self, spec: str = "heretic:local", budget: RulerBudget | None = None) -> OpenAISeat:
        seat = make_seat(spec, budget)
        seat._transport = httpx.MockTransport(self.handler)
        seat._clock = lambda: self.now
        return seat


def _chunks(text: str, size: int = 4) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


def test_request_body_streams_with_a_token_cap_and_the_schema():
    srv = FakeLlama({"content": _chunks(TEXT)}, {"content": ["hello"]})
    seat = srv.seat()
    orders, raw = seat.decide("orders prompt", timeout=5, **IDS)
    assert isinstance(orders, Orders) and orders.orders[0].to == "milan" and raw == TEXT
    assert (orders.game_id, orders.turn, orders.faction) == ("g", 3, "venice")
    body = srv.bodies[0]
    assert srv.urls[0] == "http://127.0.0.1:8090/v1/chat/completions"
    assert body["model"] == "heretic" and body["stream"] is True
    assert body["messages"] == [{"role": "user", "content": "orders prompt"}]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == 2500
    assert body["response_format"] == {"type": "json_schema",
                                       "json_schema": {"name": "orders", "schema": strict_schema()}}
    assert seat.chat("chat prompt", timeout=5) == "hello"
    assert "response_format" not in srv.bodies[1]


def test_heretic_think_reasons_first_within_its_budget():
    # live (2026-10-29): Heretic answered with thinking off and had 34-60% of its orders refused
    srv = FakeLlama({"reasoning": ["hmm"] * 10, "content": [TEXT]}, {"content": [TEXT]})
    seat = srv.seat("heretic:think")
    assert seat.name == "openai:heretic:think"
    orders, _ = seat.decide("p", timeout=420, **IDS)
    assert len(orders.orders) == 3
    assert srv.bodies[0]["chat_template_kwargs"] == {"enable_thinking": True}
    assert srv.bodies[0]["max_tokens"] == 6000 + 2500
    # a call too short to think and still answer (the Fallback's 90 s reserve) answers straight away
    seat.decide("p", timeout=90, **IDS)
    assert srv.bodies[1]["chat_template_kwargs"] == {"enable_thinking": False}


def test_bearer_header_only_with_the_key(monkeypatch):
    srv = FakeLlama({"content": ["ok"]}, {"content": ["ok"]})
    seat = srv.seat()
    monkeypatch.setenv("OPENAI_API_KEY_PARLEY", "secret-test-key")
    seat.chat("hi", timeout=5)
    assert srv.headers[0].get("authorization") == "Bearer secret-test-key"
    monkeypatch.delenv("OPENAI_API_KEY_PARLEY", raising=False)
    seat.chat("hi", timeout=5)
    assert "authorization" not in srv.headers[1]


def test_http_500_and_empty_answers_are_seat_errors():
    with pytest.raises(SeatError, match="heretic failed"):
        FakeLlama(500).seat().decide("p", timeout=5, **IDS)
    with pytest.raises(SeatError, match="heretic returned no content"):
        FakeLlama({"content": []}).seat().decide("p", timeout=5, **IDS)
    with pytest.raises(SeatError, match="heretic returned no content"):
        FakeLlama({"content": [], "raw": _sse(choices=False)}).seat().decide("p", timeout=5, **IDS)
    with pytest.raises(SeatError, match="heretic failed"):
        FakeLlama({"content": [], "raw": b'data: {"error": {"message": "boom"}}\n\n'}).seat().decide(
            "p", timeout=5, **IDS)


def test_a_server_that_ignores_stream_still_answers():
    srv = FakeLlama({"json": {"choices": [{"message": {"content": TEXT}}]}})
    orders, _ = srv.seat().decide("p", timeout=5, **IDS)
    assert len(orders.orders) == 3


@pytest.mark.parametrize("first", [503, "drop"])
def test_waits_for_the_server_and_retries_once(monkeypatch, first):
    # live: Heretic's wake from sleep failed, its container restarted, and the turn was lost
    monkeypatch.setattr(OpenAISeat, "RETRY_STEP", 0.01)
    srv = FakeLlama(first, {"content": [TEXT]})
    orders, _ = srv.seat().decide("p", timeout=5, **IDS)
    assert orders.orders[0].to == "milan"
    assert (len(srv.bodies), srv.gets) == (2, 1)


def test_gives_up_after_one_retry(monkeypatch):
    monkeypatch.setattr(OpenAISeat, "RETRY_STEP", 0.01)
    with pytest.raises(SeatError, match="503"):
        FakeLlama(503, 503).seat().decide("p", timeout=5, **IDS)


def test_thinking_past_its_token_budget_is_cut_and_the_ruler_answers_from_its_notes():
    srv = FakeLlama({"reasoning": ["I weigh Milan. "] * 50 + ["Decided: gold to Milan."] * 50, "step": 0.04},
                    {"content": _chunks(TEXT), "step": 0.04})
    seat = srv.seat("heretic:think", RulerBudget(think_tokens=100))
    orders, raw = seat.decide("orders prompt", timeout=420, **IDS)
    assert len(orders.orders) == 3 and raw == TEXT
    retry = srv.bodies[1]
    assert retry["chat_template_kwargs"] == {"enable_thinking": False} and retry["max_tokens"] == 2500
    asked = retry["messages"][0]["content"]
    assert asked.startswith("orders prompt") and "Your time to think is up" in asked
    assert "Decided: gold to Milan." in asked and "orders JSON" in asked


def test_run9_long_thinking_still_plays_inside_seat_timeout():
    # run9: 8.1k tokens at ~22 tok/s after ~15 s of prompt; seat_timeout 420 lost the whole turn.
    # Now thinking stops at 420 - 120 s and the answer (no thinking) fits in what is left.
    srv = FakeLlama({"prompt_s": 15, "reasoning": ["tok"] * 8000, "step": 1 / 22},
                    {"prompt_s": 20, "content": _chunks(TEXT, 1), "step": 1 / 19})
    seat = srv.seat("heretic:think")
    orders, _ = seat.decide("p", timeout=420, **IDS)
    assert len(orders.orders) == 3
    assert srv.now <= 420
    assert srv.bodies[1]["chat_template_kwargs"] == {"enable_thinking": False}


def test_a_deadline_mid_answer_keeps_the_finished_orders():
    # 20 s a chunk: the third order isn't finished when the 60 s run out
    first_two = TEXT.index('{"type": "send_gold", "to": "pisa"')
    parts = [TEXT[:first_two // 2], TEXT[first_two // 2:first_two], TEXT[first_two:first_two + 20],
             TEXT[first_two + 20:]]
    srv = FakeLlama({"content": parts, "step": 20})
    orders, raw = srv.seat().decide("p", timeout=60, **IDS)
    assert [o.to for o in orders.orders] == ["milan", "genoa"]
    assert raw == "".join(parts[:3])


@pytest.mark.parametrize("error", [httpx.ReadTimeout("stalled"), httpx.RemoteProtocolError("dropped")])
def test_a_stalled_or_dropped_stream_keeps_the_finished_orders(error):
    cut = TEXT.index('{"type": "send_gold", "to": "pisa"') + 20
    srv = FakeLlama({"content": [TEXT[:cut]], "raise": error})
    orders, _ = srv.seat().decide("p", timeout=60, **IDS)
    assert [o.to for o in orders.orders] == ["milan", "genoa"]


def test_a_cut_before_one_whole_order_is_a_seat_error():
    srv = FakeLlama({"content": ['{"orders": [{"type": "send_', 'gold"'], "step": 100})
    with pytest.raises(SeatError, match="ran out of time before finishing one order"):
        srv.seat().decide("p", timeout=60, **IDS)


def test_the_token_cap_keeps_the_finished_orders():
    srv = FakeLlama({"content": [TEXT[:TEXT.index('{"type": "send_gold", "to": "pisa"') + 20]], "finish": "length"})
    orders, _ = srv.seat().decide("p", timeout=60, **IDS)
    assert [o.to for o in orders.orders] == ["milan", "genoa"]


def test_inline_think_tags_count_as_thinking():
    # a server without reasoning parsing leaves <think>...</think> in the content
    srv = FakeLlama({"content": ["<th", "ink>", "plan "] + ["more "] * 20 + ["</thi", "nk>", TEXT]})
    orders, raw = srv.seat("heretic:think").decide("p", timeout=420, **IDS)
    assert len(orders.orders) == 3 and raw == TEXT
    cut = FakeLlama({"content": ["<think>", "plan "] + ["more "] * 200}, {"content": [TEXT]})
    orders, _ = cut.seat("heretic:think", RulerBudget(think_tokens=50)).decide("p", timeout=420, **IDS)
    assert len(orders.orders) == 3
    assert "plan more" in cut.bodies[1]["messages"][0]["content"]


def test_a_chat_reply_cut_by_the_deadline_keeps_its_text():
    srv = FakeLlama({"content": ["We ", "accept ", "the ", "offer"], "step": 10})
    assert srv.seat().chat("p", timeout=25) == "We accept the"


def test_salvage_json():
    assert salvage_json('{"orders": [{"a": 1}, {"b": "x}]"}, {"c":') == {"orders": [{"a": 1}, {"b": "x}]"}]}
    assert salvage_json('{"orders": [{"a": 1}], "note": "half') == {"orders": [{"a": 1}]}
    assert salvage_json('{"orders": [{"a"') is None
    assert salvage_json("no json") is None
    assert salvage_json('[{"a": 1}, {"b"') == [{"a": 1}]


def test_ruler_budget_from_the_game_and_the_seat(tmp_path):
    text = ('game_id = "g"\nturn_root = "t"\nsave_dir = "s"\n'
            '[ruler_budget]\nthink_tokens = 4000\n'
            '[seats.england]\nbrain = "heretic:think"\npersona = "K."\n'
            '[seats.france]\nbrain = "heretic:think"\npersona = "K."\n'
            '[seats.france.ruler_budget]\nthink_tokens = 3000\nanswer_reserve = 90\n')
    cfg = GameConfig.model_validate(tomllib.loads(text))
    assert cfg.budget_for("england") == RulerBudget(think_tokens=4000)
    assert cfg.budget_for("france") == RulerBudget(think_tokens=3000, answer_reserve=90)
    assert GameConfig.model_validate(tomllib.loads(text.split("[ruler_budget]")[0] + '[seats.x]\nbrain="fake"\npersona="K."\n')
                                     ).budget_for("x") == RulerBudget()
    with pytest.raises(ValueError):
        RulerBudget(think_tokens=0)
