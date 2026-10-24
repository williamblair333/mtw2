"""Scripted seat for tests and dry runs."""

import time

from parley.protocol import Orders


class FakeSeat:
    def __init__(self, script: list | None = None, delay: float = 0.0, chats: list | None = None):
        self.script = list(script or [])
        self.chats = list(chats or [])
        self.delay = delay
        self.name = "fake"

    def chat(self, prompt: str, *, timeout: float) -> str:
        item = self.chats.pop(0) if self.chats else ""
        if isinstance(item, Exception):
            raise item
        return item

    def decide(self, prompt: str, *, game_id: str, turn: int, faction: str,
               timeout: float) -> tuple[Orders, str]:
        if self.delay:
            time.sleep(self.delay)
        item = self.script.pop(0) if self.script else Orders(
            protocol=1, game_id=game_id, turn=turn, faction=faction, orders=[])
        if isinstance(item, Exception):
            raise item
        orders = item.model_copy(update={"game_id": game_id, "turn": turn, "faction": faction})
        return orders, orders.model_dump_json()
