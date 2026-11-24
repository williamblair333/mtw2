"""Local model via Ollama's chat API, with the orders schema as the output format."""

import json
import os

import httpx

from parley.protocol import Orders
from parley.seats.base import SeatError, strict_schema, to_orders


def context_for(prompt: str) -> int:
    """Context window for one call. Ollama's default (4096 on a CPU host) cuts a long prompt
    from the front without an error; ~3 chars a token plus room for the answer, at least 8192."""
    need = len(prompt) // 3 + 2048
    return max(8192, -(-need // 1024) * 1024)


class OllamaSeat:
    def __init__(self, model: str = "qwen3.5:9b", host: str | None = None):
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        self.name = f"ollama:{model}"

    def _chat(self, prompt: str, timeout: float, schema: bool) -> str:
        # Thinking models spend 30s+ before answering; turns must stay quick.
        body = {"model": self.model, "stream": False, "think": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"num_ctx": context_for(prompt)}}
        if schema:
            body["format"] = strict_schema()
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.host}/api/chat", json=body)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError) as e:
            raise SeatError(f"ollama failed: {e}") from e

    def decide(self, prompt: str, *, game_id: str, turn: int, faction: str,
               timeout: float) -> tuple[Orders, str]:
        content = self._chat(prompt, timeout, schema=True)
        return to_orders(content, game_id=game_id, turn=turn, faction=faction), content

    def chat(self, prompt: str, *, timeout: float) -> str:
        return self._chat(prompt, timeout, schema=False).strip()
