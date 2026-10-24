from parley.seats.agy import AgySeat
from parley.seats.base import Seat, SeatError
from parley.seats.claude_code import ClaudeCodeSeat
from parley.seats.fake import FakeSeat
from parley.seats.ollama import OllamaSeat
from parley.seats.script import ScriptSeat

__all__ = ["AgySeat", "ClaudeCodeSeat", "FakeSeat", "OllamaSeat", "ScriptSeat", "Seat", "SeatError",
           "make_seat"]


def make_seat(spec: str) -> Seat:
    """'claude:sonnet', 'ollama:qwen3.5:9b', 'agy:gemini-4-argon-medium' or 'fake'."""
    kind, _, model = spec.partition(":")
    if kind == "fake":
        return FakeSeat()
    if not model:
        raise ValueError(f"seat spec needs a model: {spec!r}")
    if kind == "claude":
        return ClaudeCodeSeat(model)
    if kind == "ollama":
        return OllamaSeat(model)
    if kind == "agy":
        return AgySeat(model)
    if kind == "script":
        return ScriptSeat(model)
    raise ValueError(f"unknown seat kind: {spec!r}")
