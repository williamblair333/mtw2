import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from preflight_vm_headroom import problems  # noqa: E402

# the main machine on 11-25 06:40, the morning after the freeze: 32 GB available, swap full
SWAP_FULL = "MemTotal: 48234496 kB\nMemAvailable: 33554432 kB\nSwapTotal: 7340028 kB\nSwapFree: 16992 kB\n"
TIGHT = "MemTotal: 48234496 kB\nMemAvailable: 8388608 kB\nSwapTotal: 7340028 kB\nSwapFree: 7000000 kB\n"


def test_starting_a_vm_with_little_memory_is_refused():
    assert "GiB of memory" in problems("virsh -c qemu:///system start parley-fresh", TIGHT)[0]
    assert problems("sleep 1; virt-install --name x", TIGHT)


def test_full_swap_with_memory_free_passes():
    assert problems("virsh -c qemu:///system start parley-fresh", SWAP_FULL) == []


def test_a_vm_started_over_ssh_is_not_checked_here():
    assert problems("ssh the test laptop 'virsh -c qemu:///system start parley-fresh'", TIGHT) == []


def test_other_virsh_commands_pass():
    assert problems("virsh -c qemu:///system list --all; virsh screenshot parley-fresh /tmp/a.png", TIGHT) == []
