import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from diagnosis import diagnose, DIAGNOSIS_RULES, COMPLIANCE_BLOCKED, NEEDS_CUSTOMER_ACTION
from retry_policy import evaluate, MAX_RETRIES_PER_TRANSACTION, MAX_RECOVERY_WINDOW_DAYS


def test_every_failure_reason_has_a_rule():
    # Sanity check the rules table is internally consistent
    for reason, rule in DIAGNOSIS_RULES.items():
        d = diagnose(reason)
        assert d.failure_reason == reason
        assert d.recommended_action
        assert d.rationale


def test_unknown_failure_reason_raises():
    with pytest.raises(ValueError):
        diagnose("some_totally_unknown_code")


def test_fraud_suspected_is_never_retryable():
    d = diagnose("fraud_suspected")
    assert d.root_cause_category == COMPLIANCE_BLOCKED
    assert d.retryable is False


def test_needs_customer_action_reasons_are_not_retryable():
    for reason in ["card_not_enabled_online", "upi_wrong_bank_account", "card_expired"]:
        d = diagnose(reason)
        assert d.root_cause_category == NEEDS_CUSTOMER_ACTION
        assert d.retryable is False


def test_policy_blocks_fraud_suspected_even_on_first_attempt():
    d = diagnose("fraud_suspected")
    now = datetime(2026, 9, 3, 12, 0, 0)
    decision = evaluate(
        d, attempt_number=1,
        original_txn_time=now - timedelta(hours=1),
        last_attempt_time=now - timedelta(hours=1),
        now=now,
    )
    assert decision.allowed is False


def test_policy_blocks_after_max_retries():
    d = diagnose("network_error")
    now = datetime(2026, 9, 3, 12, 0, 0)
    decision = evaluate(
        d, attempt_number=MAX_RETRIES_PER_TRANSACTION + 1,
        original_txn_time=now - timedelta(hours=2),
        last_attempt_time=now - timedelta(hours=1),
        now=now,
    )
    assert decision.allowed is False
    assert "exceeds MAX_RETRIES_PER_TRANSACTION" in decision.reason


def test_policy_blocks_after_recovery_window_expires():
    d = diagnose("network_error")
    now = datetime(2026, 9, 3, 12, 0, 0)
    decision = evaluate(
        d, attempt_number=1,
        original_txn_time=now - timedelta(days=MAX_RECOVERY_WINDOW_DAYS + 1),
        last_attempt_time=now - timedelta(hours=1),
        now=now,
    )
    assert decision.allowed is False
    assert "exceeds MAX_RECOVERY_WINDOW_DAYS" in decision.reason


def test_policy_enforces_cooldown_for_delayed_category():
    d = diagnose("insufficient_funds")  # RECOVERABLE_DELAYED, 48h cooldown
    now = datetime(2026, 9, 3, 12, 0, 0)
    decision = evaluate(
        d, attempt_number=1,
        original_txn_time=now - timedelta(hours=3),
        last_attempt_time=now - timedelta(hours=1),  # too soon
        now=now,
    )
    assert decision.allowed is False
    assert "cooldown requires" in decision.reason


def test_policy_allows_immediate_category_right_away():
    d = diagnose("network_error")  # RECOVERABLE_IMMEDIATE, 0h cooldown
    now = datetime(2026, 9, 3, 12, 0, 0)
    decision = evaluate(
        d, attempt_number=1,
        original_txn_time=now - timedelta(minutes=5),
        last_attempt_time=now - timedelta(minutes=5),
        now=now,
    )
    assert decision.allowed is True
