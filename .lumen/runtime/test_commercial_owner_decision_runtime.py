from pathlib import Path


def test_commercial_owner_decision_guardrails_are_fail_closed():
    source = Path(__file__).with_name("commercial_owner_decision_runtime.py").read_text(encoding="utf-8")
    assert 'COMMERCIAL_CLOSE_SIMULATED' in source
    assert 'financial_commitment_executed": False' in source
    assert 'actual_payment_executed": False' in source
    assert 'contract_execution": False' in source
    assert 'autonomous_spend_usd": 0' in source
    assert 'approve_and_close' in source
    assert 'rejected_no_execution' in source


def test_commercial_commands_run_before_generic_owner_commands():
    bridge = Path(__file__).with_name("conversion_loop_bridge_runtime.py").read_text(encoding="utf-8")
    commercial = bridge.index("commercial_decisions.consume_commands()")
    generic = bridge.index("owner_decisions.consume_commands()")
    guard = bridge.index("owner_decisions.install_continuous_learning_guard()")
    assert commercial < generic < guard
