import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from upstream_check import REGISTER, problems  # noqa: E402

R = "EOP-Labs/M2TWEOP-library"


def _items():
    return tomllib.loads(REGISTER.read_text())["item"]


def test_a_solved_question_still_open_upstream_is_flagged():
    # 11-25: #91 solved by 11-20, still open, and an EOP developer answered it in Discord
    items = [{"repo": R, "number": 91, "ask": "papal vote", "state": "solved", "note": "by element"}]
    p = problems(items, {(R, 91): "OPEN"}, {(R, 91)})
    assert len(p) == 1 and "#91" in p[0] and "close it" in p[0]
    assert problems(items, {(R, 91): "CLOSED"}, set()) == []


def test_an_open_upstream_item_missing_from_the_register_is_flagged():
    p = problems([], {}, {(R, 95)})
    assert p and "#95" in p[0] and "not in docs/upstream.toml" in p[0]


def test_a_waiting_item_open_upstream_is_fine():
    items = [{"repo": R, "number": 89, "ask": "bindings", "state": "waiting"}]
    assert problems(items, {(R, 89): "OPEN"}, {(R, 89)}) == []


def test_the_register_is_well_formed():
    for i in _items():
        assert i["state"] in ("waiting", "solved") and i["kind"] in ("issue", "pr") and i["ask"], i
