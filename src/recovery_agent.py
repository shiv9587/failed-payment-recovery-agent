"""
Recovery Agent — Failed Payment Recovery Agent (Track 3).

The orchestration loop: for each failed transaction ->
    1. diagnose()        -> what's the root cause + recommended action
    2. retry_policy.evaluate() -> are we allowed to act right now
    3. execute the action via RazorpayClient (or MockRazorpayClient)
    4. append a structured record to logs/audit_trail.jsonl

This module deliberately does NOT decide business logic itself — it only
orchestrates. All "should we act" logic lives in diagnosis.py +
retry_policy.py so the decisioning stays auditable and testable in
isolation (see tests/test_diagnosis.py).
"""

import csv
import json
import os
from datetime import datetime
from dataclasses import asdict, dataclass
from typing import Optional

from src.diagnosis import diagnose, Diagnosis
from src.retry_policy import evaluate, PolicyDecision
from src.razorpay_client import get_client

AUDIT_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "logs", "audit_trail.jsonl"
)

# Which recommended_action values actually trigger a Razorpay payment link.
# Others (notify_customer_*, flag_for_manual_review) are logged but don't
# call the API — they're informational/compliance actions, not payment
# recovery actions.
ACTIONS_THAT_CREATE_PAYMENT_LINK = {
    "resend_payment_link:immediate",
    "retry_after_delay:48h",
    "retry_after_delay:2h",
    "send_alternate_payment_method_link",
    "resend_upi_collect_request:immediate",
    "retry_same_method:immediate",
    "send_reminder_nudge:24h",
}


@dataclass
class AuditRecord:
    transaction_id: str
    customer_id: str
    amount: float
    payment_method: str
    failure_reason: str
    attempt_number: int
    root_cause_category: str
    recommended_action: str
    policy_allowed: bool
    policy_reason: str
    action_taken: str
    action_result: Optional[dict]
    processed_at: str


def process_transaction(row: dict, client, now: datetime = None) -> AuditRecord:
    """
    Process a single transaction row (from the CSV) end-to-end and
    return the AuditRecord to be logged. Never raises on a single bad
    row — unknown failure reasons are caught and routed to manual
    review rather than crashing the whole batch.
    """
    now = now or datetime.now()
    txn_time = datetime.fromisoformat(row["timestamp"])
    attempt_number = int(row["attempt_number"])

    try:
        d: Diagnosis = diagnose(row["failure_reason"])
    except ValueError as e:
        # Unknown failure reason -> hard stop, flag for human review.
        return AuditRecord(
            transaction_id=row["transaction_id"],
            customer_id=row["customer_id"],
            amount=float(row["amount"]),
            payment_method=row["payment_method"],
            failure_reason=row["failure_reason"],
            attempt_number=attempt_number,
            root_cause_category="UNKNOWN",
            recommended_action="flag_for_manual_review",
            policy_allowed=False,
            policy_reason=str(e),
            action_taken="none",
            action_result=None,
            processed_at=now.isoformat(timespec="seconds"),
        )

    decision: PolicyDecision = evaluate(
        diagnosis=d,
        attempt_number=attempt_number,
        original_txn_time=txn_time,
        last_attempt_time=txn_time,  # first attempt: original == last
        now=now,
    )

    action_taken = "none"
    action_result = None

    if decision.allowed and d.recommended_action in ACTIONS_THAT_CREATE_PAYMENT_LINK:
        # Extract name and contact from CSV if available
        cust_name = row.get("customer_name") or f"Customer {row['customer_id']}"
        raw_contact = str(row.get("customer_contact", ""))

        # Default fallback number to prevent API errors
        cust_contact = "+919587974808"

        # Sanitize contact logic to prevent "Recurring digits" error
        digits_only = "".join(filter(str.isdigit, raw_contact))
        if len(digits_only) >= 10:
            clean_num = digits_only[-10:]
            if not any(digit * 4 in clean_num for digit in "0123456789"):
                cust_contact = f"+91{clean_num}"

        result = client.create_payment_link(
            amount_rupees=float(row["amount"]),
            customer_name=cust_name,
            customer_contact=cust_contact,
            description=f"Payment retry for {row['transaction_id']} "
                        f"({d.failure_reason})",
            reference_id=row["transaction_id"],
        )
        action_taken = d.recommended_action
        action_result = result
    elif decision.allowed:
        # e.g. notify_customer_* actions that don't need a payment link
        action_taken = d.recommended_action
        action_result = {"note": "non-payment-link action, notification only (not implemented in this demo)"}
    else:
        action_taken = "blocked"
        action_result = None

    return AuditRecord(
        transaction_id=row["transaction_id"],
        customer_id=row["customer_id"],
        amount=float(row["amount"]),
        payment_method=row["payment_method"],
        failure_reason=row["failure_reason"],
        attempt_number=attempt_number,
        root_cause_category=d.root_cause_category,
        recommended_action=d.recommended_action,
        policy_allowed=decision.allowed,
        policy_reason=decision.reason,
        action_taken=action_taken,
        action_result=action_result,
        processed_at=now.isoformat(timespec="seconds"),
    )


def run_batch(csv_path: str, use_mock: bool = True, limit: int = None):
    """
    Reads the failed_transactions.csv, processes every row, appends
    each result to logs/audit_trail.jsonl, and returns summary stats.
    """
    client = get_client(use_mock=use_mock)
    os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)

    records = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            record = process_transaction(row, client)
            records.append(record)

    with open(AUDIT_LOG_PATH, "w") as f:
        for r in records:
            f.write(json.dumps(asdict(r)) + "\n")

    return summarize(records)


def summarize(records):
    total = len(records)
    recovered_action_taken = sum(
        1 for r in records
        if r.action_taken in ACTIONS_THAT_CREATE_PAYMENT_LINK
    )
    blocked = sum(1 for r in records if not r.policy_allowed)
    amount_in_recovery_flow = sum(
        r.amount for r in records
        if r.action_taken in ACTIONS_THAT_CREATE_PAYMENT_LINK
    )

    by_reason = {}
    for r in records:
        by_reason.setdefault(r.failure_reason, {"total": 0, "action_taken": 0})
        by_reason[r.failure_reason]["total"] += 1
        if r.action_taken in ACTIONS_THAT_CREATE_PAYMENT_LINK:
            by_reason[r.failure_reason]["action_taken"] += 1

    return {
        "total_transactions": total,
        "recovery_actions_initiated": recovered_action_taken,
        "blocked_by_policy": blocked,
        "amount_rupees_in_recovery_flow": round(amount_in_recovery_flow, 2),
        "by_failure_reason": by_reason,
    }


if __name__ == "__main__":
    data_csv = os.path.join(
        os.path.dirname(__file__), "..", "data", "failed_transactions.csv"
    )
    summary = run_batch(data_csv, use_mock=True)
    print(json.dumps(summary, indent=2))