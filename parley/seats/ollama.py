"""Local model via Ollama's chat API, with the orders schema as the output format."""

import json
import os

import httpx

from parley.protocol import Orders
from parley.seats.base import SeatError, strict_schema, to_orders


class OllamaSeat:
    def __init__(self, model: str = "qwen3.5:9b", host: str | None = None):
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        self.name = f"ollama:{model}"

    def _chat(self, prompt: str, timeout: float, schema: bool) -> str:
        # Thinking models spend 30s+ before answering; turns must stay quick.
        body = {"model": self.model, "stream": False, "think": False,
                "messages": [{"role": "user", "content": prompt}]}
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
