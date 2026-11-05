import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def private_agy_lock(tmp_path, monkeypatch):
    """Tests get their own Gemini lock: a live game holding the machine's lock mustn't stall them."""
    monkeypatch.setattr("parley.seats.agy.LOCK_PATH", tmp_path / "agy.lock")


@pytest.fixture(autouse=True)
def no_real_crash_watch(tmp_path, monkeypatch):
    """A QA process manager a test didn't configure sees an empty /proc and runs no `just` recipe:
    restore()/run_suite() tests without an injected stop_crash_watch otherwise stopped the
    machine's live crash-watch (and, with the user unit, would call the real systemctl)."""
    import subprocess

    from parley.qa import runner

    empty_proc = tmp_path / "no-proc"
    empty_proc.mkdir(exist_ok=True)
    orig_init = runner._ProcessManager.__init__

    def no_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0)

    def safe_init(self, *, proc_root=None, kill_fn=None, wait_timeout=5.0, run_fn=None):
        orig_init(
            self,
            proc_root=proc_root if proc_root is not None else empty_proc,
            kill_fn=kill_fn,
            wait_timeout=wait_timeout,
            run_fn=run_fn or no_run,
        )

    monkeypatch.setattr(runner._ProcessManager, "__init__", safe_init)


@pytest.fixture
def venice_state_dict():
    return json.loads((FIXTURES / "state_turn1_venice.json").read_text())


@pytest.fixture
def venice_report(venice_state_dict):
    from parley.protocol import StateReport

    return StateReport.model_validate(venice_state_dict)
