from parley.seats.agy import AgySeat
from parley.seats.base import RulerBudget, Seat, SeatError
from parley.seats.claude_code import ClaudeCodeSeat
from parley.seats.fake import FakeSeat
from parley.seats.ollama import OllamaSeat
from parley.seats.openai_compat import OpenAISeat
from parley.seats.script import ScriptSeat

__all__ = ["AgySeat", "ClaudeCodeSeat", "FakeSeat", "OllamaSeat", "OpenAISeat", "RulerBudget", "ScriptSeat", "Seat",
           "SeatError", "make_seat"]


def make_seat(spec: str, budget: RulerBudget | None = None) -> Seat:
    """'claude:sonnet', 'ollama:qwen3.5:9b', 'agy:gemini-4-argon-medium', 'openai:gpt-4o', 'heretic:local',
    'heretic:think' (Heretic reasons before answering) or 'fake'. `budget` bounds the streamed
    seats (heretic, openai); the others have only the call's timeout."""
    kind, _, model = spec.partition(":")
    if kind == "fake":
        return FakeSeat()
    if kind == "heretic":
        return OpenAISeat("heretic", think=model == "think", budget=budget)
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
    if kind == "openai":
        return OpenAISeat(model, budget=budget)
    raise ValueError(f"unknown seat kind: {spec!r}")

