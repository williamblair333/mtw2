"""Control areas: which parts of a realm the LLM runs, and which it leaves to the game.

A seat's `control` is a preset or a list of areas. An area not in the list belongs to the
game: its AI for an AI-run faction, its governors' auto-manage (or nobody) for the human's slot.
"""

AREAS = ("diplomacy", "armies", "agents", "build", "recruit", "taxes")

PRESETS = {
    "diplomat": ("diplomacy",),
    "ruler": ("diplomacy", "armies", "agents"),  # the default: what rulers did before areas existed
    # everything (recruiting reads the recruitment pools, never EOP 3.3.1's out-of-bounds
    # getRecruitOptions; the governors can't recruit for the human slot without a governor)
    "full": AREAS,
}

ORDER_AREA = {
    "send_gold": "diplomacy", "cede_settlement": "diplomacy", "set_stance": "diplomacy",
    "march_on": "armies", "besiege": "armies", "withdraw": "armies",
    "move_army": "armies", "attack": "armies", "merge_armies": "armies", "merge_units": "armies", "disband": "armies",
    "board": "armies", "land": "armies", "blockade": "armies",
    "move_agent": "agents", "marry": "agents",
    "build": "build", "recruit": "recruit", "retrain": "recruit", "set_tax": "taxes",
    "assassinate": "agents", "spy": "agents", "bribe": "agents", "sabotage": "agents",
}


def resolve(control: str | list[str]) -> tuple[str, ...]:
    """A preset name or a list of areas -> the areas, in AREAS order."""
    if isinstance(control, str):
        if control not in PRESETS:
            raise ValueError(f"control must be one of {', '.join(PRESETS)} or a list of areas "
                             f"({', '.join(AREAS)}), got '{control}'")
        return PRESETS[control]
    for area in control:
        if area not in AREAS:
            raise ValueError(f"unknown control area '{area}'; areas: {', '.join(AREAS)}")
    return tuple(a for a in AREAS if a in control)
