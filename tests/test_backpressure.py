from services.shared.backpressure import InflightGate


def test_inflight_gate_limits_requests() -> None:
    gate = InflightGate(2)
    assert gate.try_enter() is True
    assert gate.try_enter() is True
    assert gate.active == 2
    assert gate.try_enter() is False
    gate.leave()
    assert gate.active == 1
    assert gate.try_enter() is True
    assert gate.active == 2
    gate.leave()
    gate.leave()
    assert gate.active == 0
