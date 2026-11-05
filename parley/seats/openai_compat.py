"""OpenAI-compatible chat completions API (llama-server, vLLM, etc.), with the orders schema.

Answers stream, so a ruler that runs long still plays (STANDARDS `ruler-budget`; run9 lost 4 of 46
turns to 5-8k-token answers, ~85% of them thinking, past seat_timeout = 420):
- thinking stops after `think_tokens`, or when only `answer_reserve` seconds are left; the ruler
  is then asked again with thinking off and the end of its reasoning in the prompt;
- the answer is capped at `answer_tokens` and the call's deadline; a cut answer keeps the orders
  it finished.
"""

import json
import logging
import os
import time

import httpx

from parley.protocol import Orders
from parley.seats.base import RulerBudget, SeatError, salvage_json, strict_schema, to_orders

log = logging.getLogger(__name__)

THINK_CUT = ("\n\n---\nYour time to think is up. Your reasoning so far (its end, if it was long):\n"
             "<<<\n{notes}\n>>>\nAnswer now from it: {what}.")


class _Unready(Exception):
    """The server isn't answering yet (503 while it loads, or a dropped connection before a byte)."""

    def __init__(self, resp: httpx.Response | None = None):
        super().__init__("not ready")
        self.resp = resp


class OpenAISeat:
    RETRY_STEP = 3.0  # seconds between /health polls while the server comes back
    MIN_THINK = 60.0  # a thinking window shorter than this isn't worth it: answer straight away
    NOTES_CHARS = 12000  # the end of a cut reasoning handed to the answer call (~3-4k tokens)

    def __init__(self, model: str, host: str | None = None, think: bool = False,
                 budget: RulerBudget | None = None, transport: httpx.BaseTransport | None = None):
        self.model = model
        self.host = (host or os.environ.get("PARLEY_OPENAI_HOST") or "http://127.0.0.1:8090/v1").rstrip("/")
        self.think = think  # let a reasoning model (Qwen 3.6) think before it answers
        self.name = f"openai:{model}" + (":think" if think else "")
        self.budget = budget or RulerBudget()
        self._transport = transport  # tests: a fake server
        self._clock = time.monotonic

    def _body(self, prompt: str, schema: bool, think: bool) -> dict:
        b = self.budget
        body = {
            "model": self.model,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
            "chat_template_kwargs": {"enable_thinking": think},
            # the server stops on its own too, should the client vanish mid-answer
            "max_tokens": b.answer_tokens + (b.think_tokens if think else 0),
        }
        if schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "orders", "schema": strict_schema()},
            }
        return body

    def _chat(self, prompt: str, timeout: float, schema: bool) -> tuple[str, bool]:
        """The answer's text, and whether it was cut short (deadline, token cap or dropped)."""
        deadline = self._clock() + timeout
        think = self.think and timeout - self.budget.answer_reserve >= self.MIN_THINK
        headers = {}
        api_key = os.environ.get("OPENAI_API_KEY_PARLEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            with httpx.Client(transport=self._transport) as client:
                think_until = deadline - self.budget.answer_reserve if think else None
                start = self._clock()
                reasoning, content, why = self._call(client, self._body(prompt, schema, think),
                                                     headers, deadline, think_until)
                if why == "think":
                    log.warning("%s: thinking cut after %d chunks, %.0f s; answering without it",
                                self.name, len(reasoning), self._clock() - start)
                    notes = "".join(reasoning)[-self.NOTES_CHARS:]
                    what = "the orders JSON, nothing else" if schema else "your reply, nothing else"
                    retry = prompt + THINK_CUT.format(notes=notes, what=what)
                    _, content, why = self._call(client, self._body(retry, schema, False), headers, deadline)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError) as e:
            raise SeatError(f"{self.model} failed: {e}") from e  # "heretic failed", not "openai"
        text = "".join(content)
        if not text.strip():
            raise SeatError(f"{self.model} returned no content"
                            + (" before its time ran out" if why == "cut" else ""))
        if why in ("cut", "length"):
            log.warning("%s: answer cut short (%s) after %d characters", self.name,
                        "deadline" if why == "cut" else "token cap", len(text))
        return text, why in ("cut", "length")

    def _call(self, client: httpx.Client, body: dict, headers: dict, deadline: float,
              think_until: float | None = None) -> tuple[list[str], list[str], str]:
        try:
            return self._stream(client, body, headers, deadline, think_until)
        except _Unready:
            # llama-server answers 503 while it loads, and drops the connection when its wake
            # from sleep fails and the container restarts (live, 2026-10-26): wait, retry once
            self._wait_ready(client, deadline)
            try:
                return self._stream(client, body, headers, deadline, think_until)
            except _Unready as e:
                if e.resp is not None:
                    e.resp.raise_for_status()
                raise httpx.ConnectError("server not ready") from e

    def _stream(self, client: httpx.Client, body: dict, headers: dict, deadline: float,
                think_until: float | None) -> tuple[list[str], list[str], str]:
        """One streamed call: (reasoning chunks, content chunks, why it ended). `why` is 'done',
        'length' (the token cap), 'think' (thinking ran past its budget: the stream is dropped,
        which cancels the task on llama-server) or 'cut' (the deadline came, or the connection
        dropped, mid-answer: what arrived is kept)."""
        reasoning, content = [], []
        # a server that leaves <think>...</think> in the content: None until the content shows
        inline: bool | None = None
        why = "done"
        left = max(1.0, deadline - self._clock())
        try:
            with client.stream("POST", f"{self.host}/chat/completions", json=body, headers=headers,
                               timeout=httpx.Timeout(left, connect=min(10.0, left))) as resp:
                if resp.status_code == 503:
                    raise _Unready(resp)
                resp.raise_for_status()
                if resp.headers.get("content-type", "").startswith("application/json"):
                    resp.read()  # a server that ignored "stream": the whole answer at once
                    message = resp.json()["choices"][0]["message"]
                    return [message.get("reasoning_content") or ""], [message.get("content") or ""], "done"
                for line in resp.iter_lines():
                    if line.startswith("data:") and (data := line[5:].strip()) != "[DONE]":
                        chunk = json.loads(data)
                        if chunk.get("error"):
                            raise SeatError(f"{self.model} failed: {chunk['error']}")
                        choice = (chunk.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        if delta.get("reasoning_content"):
                            reasoning.append(delta["reasoning_content"])
                        if delta.get("content"):
                            content.append(delta["content"])
                            if inline is None:
                                head = "".join(content).lstrip()
                                if len(head) >= 7 or not "<think>".startswith(head):
                                    inline = head.startswith("<think>")
                            if inline:  # still inside the inline <think>: the content is reasoning
                                reasoning.extend(content)
                                content = []
                                if "</think>" in "".join(reasoning[-4:]):
                                    inline = False
                                    before, _, after = "".join(reasoning).partition("</think>")
                                    reasoning, content = [before], ([after] if after else [])
                        if choice.get("finish_reason") == "length":
                            why = "length"
                    elif line.startswith("data:"):
                        break
                    now = self._clock()
                    thinking = inline is True or (inline is None and bool(reasoning))
                    if (think_until is not None and thinking
                            and (len(reasoning) >= self.budget.think_tokens or now >= think_until)):
                        return reasoning, content, "think"
                    if now >= deadline:
                        return reasoning, content, "cut"
        except _Unready:
            raise
        except (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError) as e:
            if not reasoning and not content and not isinstance(e, httpx.ReadTimeout):
                raise _Unready() from e
            return reasoning, content, "cut"
        except httpx.ConnectError as e:
            raise _Unready() from e
        return reasoning, content, why

    def _wait_ready(self, client: httpx.Client, deadline: float) -> None:
        """Poll the server's /health (beside /v1) until it answers 200, within the seat's deadline."""
        health = self.host.removesuffix("/v1") + "/health"
        while self._clock() < deadline - self.RETRY_STEP:
            try:
                if client.get(health, timeout=self.RETRY_STEP).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(self.RETRY_STEP)

    def decide(self, prompt: str, *, game_id: str, turn: int, faction: str,
               timeout: float) -> tuple[Orders, str]:
        content, cut = self._chat(prompt, timeout, schema=True)
        if not cut:
            return to_orders(content, game_id=game_id, turn=turn, faction=faction), content
        kept = salvage_json(content)  # never _extract_json: it would take the first whole order
        if kept is None:
            raise SeatError(f"{self.model} ran out of time before finishing one order")
        orders = to_orders(kept, game_id=game_id, turn=turn, faction=faction)
        log.warning("%s %s turn %d: kept %d orders from a cut answer", self.name, faction, turn,
                    len(orders.orders))
        return orders, content

    def chat(self, prompt: str, *, timeout: float) -> str:
        return self._chat(prompt, timeout, schema=False)[0].strip()
