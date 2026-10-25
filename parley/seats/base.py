"""What every brain behind a faction looks like."""

import json
import os
import tempfile
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from parley.protocol import Order, OrderResult, Orders, Say, orders_json_schema


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


def _unfence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text


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
            payload = json.loads(_unfence(payload))
        except json.JSONDecodeError as e:
            raise SeatError(f"answer is not JSON: {e}") from e
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
    note = payload.get("note")
    orders = Orders(protocol=1, game_id=game_id, turn=turn, faction=faction, orders=kept,
                    messages=messages, note=note if isinstance(note, str) else "")
    orders.source_index, orders.malformed = source, malformed
    return orders
