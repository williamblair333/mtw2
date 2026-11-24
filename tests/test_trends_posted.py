"""Trend alerts reach the humans' audit channel once each (STANDARDS trend-alerts)."""

from pathlib import Path
from types import SimpleNamespace

from parley.orchestrator import Orchestrator
from tests.test_trends import _make_turn


class _Store:
    def __init__(self):
        self.queued = []

    def queue(self, game_id, turn, channel, sender, text, kind=None):
        self.queued.append((channel, text))


def _orch(root: Path) -> Orchestrator:
    o = Orchestrator.__new__(Orchestrator)
    o.config = SimpleNamespace(turn_root=root, game_id="g")
    o.store = _Store()
    return o


def test_a_new_trend_alert_is_posted_once(tmp_path):
    for t, towns in ((1, 3), (2, 3), (3, 3), (4, 2)):
        _make_turn(tmp_path, "g", t, "england", orders_count=5, applied_ok=5, refused=0,
                   answer_seconds=20.0, towns=towns, armies=3)
    o = _orch(tmp_path)
    o._post_new_trends(4)
    assert o.store.queued == [("audit", "[trend] england: towns fell from 3 to 2")]
    # the next turn, and a restarted loop, don't post it again
    _make_turn(tmp_path, "g", 5, "england", orders_count=5, applied_ok=5, refused=0,
               answer_seconds=20.0, towns=2, armies=3)
    o._post_new_trends(5)
    o2 = _orch(tmp_path)
    o2._post_new_trends(5)
    assert len(o.store.queued) == 1 and o2.store.queued == []


def test_no_alerts_post_nothing(tmp_path):
    for t in range(1, 5):
        _make_turn(tmp_path, "g", t, "england", orders_count=5, applied_ok=5, refused=0,
                   answer_seconds=20.0, towns=3, armies=3)
    o = _orch(tmp_path)
    o._post_new_trends(4)
    assert o.store.queued == []
