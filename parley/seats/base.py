"""What every brain behind a faction looks like."""

import json
import os
import tempfile
from typing import Protocol

from pydantic import ValidationError

from parley.protocol import Orders, orders_json_schema


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


def to_orders(payload, *, game_id: str, turn: int, faction: str) -> Orders:
    """Parse the LLM's payload; identity fields always come from the turn, never the LLM."""
    if isinstance(payload, str):
        try:
            payload = json.loads(_unfence(payload))
        except json.JSONDecodeError as e:
            raise SeatError(f"answer is not JSON: {e}") from e
    if not isinstance(payload, dict):
        raise SeatError("answer is not a JSON object")
    payload = {**payload, "protocol": 1, "game_id": game_id, "turn": turn, "faction": faction}
    try:
        return Orders.model_validate(payload)
    except ValidationError as e:
        raise SeatError(f"answer breaks the orders schema: {e}") from e
