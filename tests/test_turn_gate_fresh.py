from test_orchestrator import FakeSeat, _config, _orders, _pending

from parley.orchestrator import Orchestrator
from parley.protocol import SendGold
from parley.store import adviser_channel


def _gated(tmp_path, venice_state_dict, turn=1):
    cfg = _config(tmp_path, ("venice",))
    cfg.seats["venice"].ladder = True
    cfg.seats["venice"].quiet_brain = "agy:gemini-3.8-flash-low"
    _pending(cfg, "venice", {**venice_state_dict, "turn": turn}, turn=turn)
    ruler = FakeSeat([_orders(SendGold(to="milan", amount=500))])
    quiet = FakeSeat([_orders(SendGold(to="milan", amount=100))])
    return Orchestrator(cfg, {"venice": ruler}, quiet_seats={"venice": quiet}), ruler, quiet


def test_the_rulers_own_and_old_messages_keep_a_turn_quiet(tmp_path, venice_state_dict):
    # live, 2026-10-26: the ruler's own adviser reports (and any message ever) escalated every turn
    orch, ruler, quiet = _gated(tmp_path, venice_state_dict, turn=3)
    orch.store.record(orch.config.game_id, 2, adviser_channel("venice"), "venice", "I took Rennes.")
    orch.store.record(orch.config.game_id, 0, "lobby", "milan", "Greetings.")
    assert orch.run_once() == 1
    assert len(quiet.timeouts) == 1 and len(ruler.timeouts) == 0


def test_a_new_message_from_someone_else_goes_to_the_ruler(tmp_path, venice_state_dict):
    orch, ruler, quiet = _gated(tmp_path, venice_state_dict, turn=3)
    orch.store.record(orch.config.game_id, 2, adviser_channel("venice"), "adviser:venice", "Watch the Danes.")
    assert orch.run_once() == 1
    assert len(ruler.timeouts) == 1 and len(quiet.timeouts) == 0
