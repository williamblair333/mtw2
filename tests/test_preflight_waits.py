import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from preflight_waits import problems  # noqa: E402

# the 11-21 queue on tc, as it ran (hung 12:19-15:28)
HUNG = ("ssh tc 'until grep -q \"click coverage:\" /tmp/a.out; do sleep 20; done; "
        "while pgrep -f \"[p]ython3 scripts/click_coverage.py\" >/dev/null; do sleep 5; done; "
        "cd /x; python3 scripts/click_coverage.py'")


def test_the_hung_queue_is_refused_for_both_reasons():
    p = problems(HUNG)
    assert any("find itself" in x for x in p) and any("no deadline" in x for x in p), p


def test_a_pgrep_pattern_found_nowhere_else_passes():
    assert problems("pgrep -f '[j]ust qa' | head") == []


def test_a_pgrep_x_by_name_is_not_checked():
    assert problems("pgrep -x python3; echo python3") == []


def test_a_wait_with_a_deadline_passes():
    cmd = ("start=$(date +%s); while :; do grep -q DONE f && break; "
           "[ $(( $(date +%s)-start )) -gt 600 ] && { echo STALLED; break; }; sleep 30; done")
    assert problems(cmd) == []


def test_prose_naming_pgrep_is_not_a_pgrep():
    # the gate's own commit message, refused by the first version
    assert problems('git commit -m "its pgrep -f matched its own bash -c line"') == []


def test_a_plain_command_passes():
    assert problems("git status --short") == []
