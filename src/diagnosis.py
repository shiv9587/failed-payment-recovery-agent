"""
Diagnosis engine — Failed Payment Recovery Agent (Track 3).

Pure, explainable rules-based mapping from a Razorpay-style failure_reason
to a root cause classification and a recommended recovery action.

Deliberately NOT ML-based: for a financial decisioning system, an
auditable rules engine is more defensible than a black-box classifier,
and the panel explicitly values explainability over generation speed.

Every diagnosis returns:
    - root_cause_category : one of RECOVERABLE_IMMEDIATE, RECOVERABLE_DELAYED,
                             RECOVERABLE_ALT_METHOD, NEEDS_CUSTOMER_ACTION,
                             COMPLIANCE_BLOCKED
    - recommended_action  : what the agent should do next
    - retryable           : bool — whether retry_policy should even be consulted
    - rationale            : human-readable reason, goes straight into the audit log
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnosis:
    failure_reason: str
    root_cause_category: str
    recommended_action: str
    retryable: bool
    rationale: str


# Root cause categories
RECOVERABLE_IMMEDIATE = "RECOVERABLE_IMMEDIATE"
RECOVERABLE_DELAYED = "RECOVERABLE_DELAYED"
RECOVERABLE_ALT_METHOD = "RECOVERABLE_ALT_METHOD"
NEEDS_CUSTOMER_ACTION = "NEEDS_CUSTOMER_ACTION"
COMPLIANCE_BLOCKED = "COMPLIANCE_BLOCKED"

# The rules table — maps 1:1 to data/failure_codes.md
DIAGNOSIS_RULES = {
    "insufficient_funds": dict(
        root_cause_category=RECOVERABLE_DELAYED,
        recommended_action="retry_after_delay:48h",
        retryable=True,
        rationale="Customer likely lacks balance now; retrying after a "
                   "delay (e.g. payday-adjacent window) improves odds "
                   "without spamming the customer.",
    ),
    "incorrect_otp": dict(
        root_cause_category=RECOVERABLE_IMMEDIATE,
        recommended_action="resend_payment_link:immediate",
        retryable=True,
        rationale="Simple entry error; customer can usually complete "
                   "correctly on the very next attempt.",
    ),
    "card_declined_by_bank": dict(
        root_cause_category=RECOVERABLE_ALT_METHOD,
        recommended_action="send_alternate_payment_method_link",
        retryable=True,
        rationale="Bank gives no specific reason (opaque decline); "
                   "retrying the same card is low-probability, so we "
                   "offer an alternate payment method instead.",
    ),
    "card_not_enabled_online": dict(
        root_cause_category=NEEDS_CUSTOMER_ACTION,
        recommended_action="notify_customer_enable_card_online",
        retryable=False,
        rationale="Requires the customer to enable online transactions "
                   "with their bank first; an automated retry cannot fix this.",
    ),
    "fraud_suspected": dict(
        root_cause_category=COMPLIANCE_BLOCKED,
        recommended_action="flag_for_manual_review",
        retryable=False,
        rationale="Bank-flagged fraud suspicion. Compliance-critical: "
                   "never auto-retry a fraud-suspected transaction.",
    ),
    "upi_collect_expired": dict(
        root_cause_category=RECOVERABLE_IMMEDIATE,
        recommended_action="resend_upi_collect_request:immediate",
        retryable=True,
        rationale="Customer simply took too long; an immediate fresh "
                   "collect request usually succeeds.",
    ),
    "upi_bank_downtime": dict(
        root_cause_category=RECOVERABLE_DELAYED,
        recommended_action="retry_after_delay:2h",
        retryable=True,
        rationale="Partner bank outage is typically transient; short "
                   "delayed retry avoids compounding load during downtime.",
    ),
    "upi_wrong_bank_account": dict(
        root_cause_category=NEEDS_CUSTOMER_ACTION,
        recommended_action="notify_customer_select_correct_account",
        retryable=False,
        rationale="Customer selected an unregistered account; agent "
                   "cannot guess the correct one, must ask the customer.",
    ),
    "network_error": dict(
        root_cause_category=RECOVERABLE_IMMEDIATE,
        recommended_action="retry_same_method:immediate",
        retryable=True,
        rationale="Transient gateway/network blip; immediate retry on "
                   "the same method is standard and effective.",
    ),
    "customer_cancelled": dict(
        root_cause_category=RECOVERABLE_DELAYED,
        recommended_action="send_reminder_nudge:24h",
        retryable=True,
        rationale="Customer may have been interrupted or hesitant; a "
                   "gentle reminder after a day performs better than "
                   "an immediate re-charge attempt.",
    ),
    "card_expired": dict(
        root_cause_category=NEEDS_CUSTOMER_ACTION,
        recommended_action="notify_customer_update_card",
        retryable=False,
        rationale="Card is expired; no retry can succeed until the "
                   "customer provides a new payment method.",
    ),
}


def diagnose(failure_reason: str) -> Diagnosis:
    """
    Map a failure_reason string to a Diagnosis. Raises ValueError on an
    unknown code rather than silently guessing — an unrecognized failure
    reason should surface for human review, not be misclassified.
    """
    rule = DIAGNOSIS_RULES.get(failure_reason)
    if rule is None:
        raise ValueError(
            f"Unknown failure_reason '{failure_reason}' — no diagnosis rule "
            f"defined. Route to manual review rather than guessing."
        )
    return Diagnosis(failure_reason=failure_reason, **rule)


if __name__ == "__main__":
    # quick manual smoke test
    for reason in DIAGNOSIS_RULES:
        d = diagnose(reason)
        print(f"{reason:<25} -> {d.root_cause_category:<22} "
              f"action={d.recommended_action:<38} retryable={d.retryable}")
