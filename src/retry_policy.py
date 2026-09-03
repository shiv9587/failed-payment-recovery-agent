"""
Retry policy — Failed Payment Recovery Agent (Track 3).

Enforces the *stopping rules* that make automated recovery safe and
compliant:
    - Hard cap on number of retries per transaction/customer
    - Minimum cooldown between attempts (varies by root cause)
    - Absolute cutoff window (no retries after N days)
    - Hard compliance block for COMPLIANCE_BLOCKED / NEEDS_CUSTOMER_ACTION
      diagnoses, regardless of how "retryable" looks elsewhere

This module is deliberately separate from diagnosis.py: diagnosis decides
*what action would help*, retry_policy decides *whether we're allowed to
take it right now*. Keeping them separate makes both easier to audit
and to defend in the pitch ("here is exactly where we stop, and why").
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.diagnosis import (
    Diagnosis,
    COMPLIANCE_BLOCKED,
    NEEDS_CUSTOMER_ACTION,
    RECOVERABLE_DELAYED,
    RECOVERABLE_IMMEDIATE,
    RECOVERABLE_ALT_METHOD,
)

MAX_RETRIES_PER_TRANSACTION = 2
MAX_RECOVERY_WINDOW_DAYS = 7

# Cooldown before the NEXT retry is allowed, keyed by root cause category.
# (This is "minimum time since last attempt", not the same as the initial
# delayed-action delay chosen in diagnosis.py — this is the floor the
# policy enforces on top of whatever diagnosis recommends.)
COOLDOWN_HOURS = {
    RECOVERABLE_IMMEDIATE: 0,
    RECOVERABLE_DELAYED: 48,
    RECOVERABLE_ALT_METHOD: 6,
}

# Categories that must NEVER be retried automatically, no matter what.
HARD_BLOCK_CATEGORIES = {COMPLIANCE_BLOCKED, NEEDS_CUSTOMER_ACTION}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


def evaluate(
    diagnosis: Diagnosis,
    attempt_number: int,
    original_txn_time: datetime,
    last_attempt_time: datetime,
    now: datetime = None,
) -> PolicyDecision:
    """
    Decide whether a retry/action is currently allowed for this transaction.

    Args:
        diagnosis: output of diagnosis.diagnose()
        attempt_number: how many attempts (including the original failure)
                        have happened so far
        original_txn_time: timestamp of the very first failed attempt
        last_attempt_time: timestamp of the most recent attempt/action
        now: override for "current time" (testability); defaults to
             datetime.now()
    """
    now = now or datetime.now()

    # 1. Hard compliance / needs-customer-action block — never auto-retry.
    if diagnosis.root_cause_category in HARD_BLOCK_CATEGORIES:
        return PolicyDecision(
            allowed=False,
            reason=f"Blocked: root_cause_category="
                   f"{diagnosis.root_cause_category} is never auto-retried "
                   f"(compliance or requires customer action).",
        )

    # 2. Diagnosis itself may mark something non-retryable.
    if not diagnosis.retryable:
        return PolicyDecision(
            allowed=False,
            reason="Blocked: diagnosis marked this failure as not retryable.",
        )

    # 3. Max retry count.
    if attempt_number > MAX_RETRIES_PER_TRANSACTION:
        return PolicyDecision(
            allowed=False,
            reason=f"Blocked: attempt_number={attempt_number} exceeds "
                   f"MAX_RETRIES_PER_TRANSACTION="
                   f"{MAX_RETRIES_PER_TRANSACTION}.",
        )

    # 4. Absolute recovery window cutoff.
    days_since_original = (now - original_txn_time).days
    if days_since_original > MAX_RECOVERY_WINDOW_DAYS:
        return PolicyDecision(
            allowed=False,
            reason=f"Blocked: {days_since_original} days since original "
                   f"failure exceeds MAX_RECOVERY_WINDOW_DAYS="
                   f"{MAX_RECOVERY_WINDOW_DAYS}.",
        )

    # 5. Cooldown since last attempt.
    cooldown_hours = COOLDOWN_HOURS.get(diagnosis.root_cause_category, 0)
    hours_since_last = (now - last_attempt_time).total_seconds() / 3600
    if hours_since_last < cooldown_hours:
        return PolicyDecision(
            allowed=False,
            reason=f"Blocked: only {hours_since_last:.1f}h since last "
                   f"attempt, cooldown requires {cooldown_hours}h for "
                   f"{diagnosis.root_cause_category}.",
        )

    return PolicyDecision(
        allowed=True,
        reason="Allowed: passes compliance, retry-count, window, and "
               "cooldown checks.",
    )


if __name__ == "__main__":
    from src.diagnosis import diagnose

    now = datetime(2026, 9, 3, 12, 0, 0)
    original = now - timedelta(days=1)
    last_attempt = now - timedelta(hours=1)

    for reason in [
        "insufficient_funds", "fraud_suspected", "network_error",
        "upi_wrong_bank_account",
    ]:
        d = diagnose(reason)
        decision = evaluate(d, attempt_number=1,
                             original_txn_time=original,
                             last_attempt_time=last_attempt, now=now)
        print(f"{reason:<25} allowed={decision.allowed!s:<6} {decision.reason}")
