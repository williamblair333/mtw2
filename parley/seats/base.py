"""What every brain behind a faction looks like."""

import json
import os
import tempfile
from typing import Protocol

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from parley.protocol import Order, OrderResult, Orders, Say, orders_json_schema


class RulerBudget(BaseModel):
    """How long a streamed ruler may think and write (STANDARDS `ruler-budget`).

    Run9 (Heretic with thinking on, both slots busy, 19-25 tok/s): answers of 5-8.2k tokens took
    210-360 s, and 4 of 46 turns ran past seat_timeout = 420 and were lost. The orders JSON itself
    was at most 4.7 KB (~1.5k tokens): the rest was thinking. So thinking is cut at `think_tokens`,
    or when only `answer_reserve` seconds are left, and the ruler answers again with thinking off
    and its reasoning so far; the answer is capped at `answer_tokens` and keeps the orders it
    finished when the deadline cuts it."""

    think_tokens: int = Field(6000, gt=0)  # thinking past this is cut (run9: ~4.5-7k thinking tokens)
    answer_tokens: int = Field(2500, gt=0)  # the orders JSON (run9: at most ~1.5k tokens)
    # seconds kept for the answer after a cut: ~1.5k tokens at 19 tok/s (79 s) + re-reading the prompt
    answer_reserve: float = Field(120, gt=0)


_SECRET_MARKERS = ("TOKEN", "KEY", "SECRET", "PASSWORD")


def safe_env() -> dict[str, str]:
    """The environment for an LLM CLI: everything except secrets (bot token, API keys).

    Discord text reaches these prompts, and agy is an agent with tools: it must never be able
    to read a secret from its environment.
    """
    return {k: v for k, v in os.environ.items() if not any(m in k.upper() for m in _SECRET_MARKERS)}


def empty_workdir() -> str:
    """A fresh empty directory to run an LLM CLI in, away from the repo and its env file."""
    return tempfile.mkdtemp(prefix="parley-seat-")


class SeatError(Exception):
    """The seat couldn't produce orders: timeout, process error or unparseable output."""


class SeatLimit(SeatError):
    """The seat's account hit a usage limit: nothing will answer until it resets, so the game
    pauses rather than play on without its rulers (seen live: every Claude seat failing for
    an hour while autoplay ended turns and declined every offer)."""


class Seat(Protocol):
    name: str

    def decide(self, prompt: str, *, game_id: str, turn: int, faction: str,
               timeout: float) -> tuple[Orders, str]: ...

    def chat(self, prompt: str, *, timeout: float) -> str:
        """Free-text reply, in character; raises SeatError like decide."""
        ...


def _strict(node):
    """Drop keywords strict structured-output validators reject; oneOf becomes anyOf.

    An order's "type" has a default in the models, so the schema marks it optional;
    constrained decoders (Ollama) then leave it out. Make it required.
    """
    if isinstance(node, dict):
        out = {("anyOf" if k == "oneOf" else k): _strict(v)
               for k, v in node.items() if k != "discriminator"}
        if "const" in out.get("properties", {}).get("type", {}):
            out["required"] = sorted(set(out.get("required", [])) | {"type"})
        return out
    if isinstance(node, list):
        return [_strict(v) for v in node]
    return node


BOOKKEEPING = ("protocol", "game_id", "turn", "faction")  # filled in by to_orders, not the LLM


def strict_schema() -> dict:
    schema = _strict(orders_json_schema())
    for field in BOOKKEEPING:
        schema["properties"].pop(field, None)
    schema["required"] = [f for f in schema.get("required", []) if f not in BOOKKEEPING]
    return schema


def schema_text() -> str:
    return json.dumps(strict_schema(), separators=(",", ":"))


def _extract_json(text: str):
    """The answer's JSON, wherever a chatty model put it: the whole text, else the last fenced
    block that parses (an example quoted first loses to the real answer), else the first object
    or array found in the prose. Raises JSONDecodeError when there is none."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    blocks = text.split("```")[1::2]
    for block in reversed(blocks):
        body = block.split("\n", 1)[1] if "\n" in block and not block.lstrip().startswith(("{", "[")) else block
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            continue
    decoder = json.JSONDecoder()
    for pos, ch in enumerate(text):
        if ch in "{[":
            try:
                value, _ = decoder.raw_decode(text, pos)
            except json.JSONDecodeError:
                continue
            if isinstance(value, (dict, list)):
                return value
    raise json.JSONDecodeError("no JSON found", text, 0)


def salvage_json(text: str):
    """What a cut-off JSON answer finished: the longest prefix that parses once its open brackets
    are closed (the orders written before the deadline). None when not one value closed."""
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        return None
    start = min(starts)
    stack, in_str, esc, cuts = [], False, False, []
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack.pop() != ch:
                break
            cuts.append((i + 1, "".join(reversed(stack))))
            if not stack:
                break
    for end, closers in reversed(cuts):
        try:
            return json.loads(text[start:end] + closers)
        except json.JSONDecodeError:
            continue
    return None


# Key slips models make despite the schema (Gemini Flash under agy isn't held to it)
ORDER_KEYS = {"action": "type", "order": "type", "kind": "type", "order_type": "type"}
SAY_KEYS = {"content": "text", "message": "text", "body": "text", "recipient": "to", "target": "to"}
_ORDER = TypeAdapter(Order)


def _renamed(item, aliases: dict[str, str]):
    if not isinstance(item, dict):
        return item
    out = dict(item)
    for old, new in aliases.items():
        if old in out and new not in out:
            out[new] = out.pop(old)
    return out


def _first_error(e: ValidationError) -> str:
    err = e.errors()[0]
    where = ".".join(str(p) for p in err["loc"])
    return f"malformed: {where + ': ' if where else ''}{err['msg']}"


def to_orders(payload, *, game_id: str, turn: int, faction: str) -> Orders:
    """Parse the LLM's payload; identity fields always come from the turn, never the LLM.

    Salvages what it can: common key slips are repaired, and each order and message is checked
    on its own, so one malformed item costs only itself. Dropped orders come back on the result
    as `malformed` (in the LLM's own numbering) and `source_index` maps kept orders to it."""
    if isinstance(payload, str):
        try:
            payload = _extract_json(payload)
        except json.JSONDecodeError as e:
            raise SeatError(f"answer is not JSON: {e}") from e
    if isinstance(payload, list):  # the orders alone, without the object around them
        payload = {"orders": payload}
    if not isinstance(payload, dict):
        raise SeatError("answer is not a JSON object")
    kept, source, malformed = [], [], []
    raw_orders = payload.get("orders")
    for i, item in enumerate(raw_orders if isinstance(raw_orders, list) else []):
        item = _renamed(item, ORDER_KEYS)
        try:
            kept.append(_ORDER.validate_python(item))
            source.append(i)
        except ValidationError as e:
            kind = str(item.get("type", "?")) if isinstance(item, dict) else "?"
            malformed.append(OrderResult(index=i, type=kind, ok=False, reason=_first_error(e)))
    messages = []
    raw_messages = payload.get("messages")
    for i, item in enumerate(raw_messages if isinstance(raw_messages, list) else []):
        try:
            messages.append(Say.model_validate(_renamed(item, SAY_KEYS)))
        except ValidationError as e:
            malformed.append(OrderResult(index=i, type="say", ok=False, reason=_first_error(e)))
    note, plan = payload.get("note"), payload.get("plan")
    if isinstance(plan, list):  # a list of goals instead of one text
        plan = "\n".join(str(g) for g in plan)
    hold = payload.get("hold_empty")
    if isinstance(hold, str):
        hold = [hold]
    orders = Orders(protocol=1, game_id=game_id, turn=turn, faction=faction, orders=kept,
                    messages=messages, note=note if isinstance(note, str) else "",
                    plan=plan if isinstance(plan, str) else "",
                    hold_empty=[h for h in hold if isinstance(h, str)] if isinstance(hold, list) else [])
    orders.source_index, orders.malformed = source, malformed
    return orders
