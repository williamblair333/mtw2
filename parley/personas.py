"""The persona library: reusable characters in personas/*.toml, one table per persona.

    [rules-lawyer]
    name = "Lord Ambrose"          # how the ruler signs messages
    kind = "archetype"             # "archetype" (permanent character) or "historic"
    faction = "england"            # optional: the faction a historic persona belongs to
    persona = "You win by ..."     # the text that opens every prompt

A game seat uses one with persona = "@rules-lawyer".
"""

import tomllib
from pathlib import Path

from pydantic import BaseModel


class Persona(BaseModel):
    id: str
    name: str
    kind: str = "archetype"
    faction: str = ""
    persona: str


def load_personas(directory: Path) -> dict[str, Persona]:
    personas = {}
    for path in sorted(Path(directory).glob("*.toml")):
        for pid, data in tomllib.loads(path.read_text(encoding="utf-8")).items():
            personas[pid] = Persona(id=pid, **data)
    return personas
