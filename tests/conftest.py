import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def venice_state_dict():
    return json.loads((FIXTURES / "state_turn1_venice.json").read_text())


@pytest.fixture
def venice_report(venice_state_dict):
    from parley.protocol import StateReport

    return StateReport.model_validate(venice_state_dict)
