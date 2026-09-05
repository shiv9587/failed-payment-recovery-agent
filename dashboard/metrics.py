"""
Metrics module — Failed Payment Recovery Agent (Track 3).

Reads logs/audit_trail.jsonl and computes the numbers that matter for
the pitch: recovery rate, amount recovered/in-flow, breakdown by
failure reason, and the "blocked" cases (which prove the compliance
logic is real, not just claimed).

Kept separate from dashboard/app.py so these functions can also be
unit-tested or reused in a CLI summary without pulling in Streamlit.
"""

import json
import os
from collections import defaultdict

AUDIT_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "logs", "audit_trail.jsonl"
)

# Mirror of recovery_agent.ACTIONS_THAT_CREATE_PAYMENT_LINK so this module
# doesn't need to import recovery_agent (keeps dashboard dependency-light).
PAYMENT_LINK_ACTIONS = {
    "resend_payment_link:immediate",
    "retry_after_delay:48h",
    "retry_after_delay:2h",
    "send_alternate_payment_method_link",
    "resend_upi_collect_request:immediate",
    "retry_same_method:immediate",
    "send_reminder_nudge:24h",
}


def load_audit_trail(path: str = AUDIT_LOG_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def compute_summary(records: list[dict]) -> dict:
    total = len(records)
    if total == 0:
        return {
            "total_transactions": 0,
            "recovery_actions_initiated": 0,
            "blocked_by_policy": 0,
            "amount_total": 0.0,
            "amount_in_recovery_flow": 0.0,
            "recovery_initiation_rate_pct": 0.0,
            "by_failure_reason": {},
            "by_root_cause_category": {},
        }

    recovery_initiated = [r for r in records if r["action_taken"] in PAYMENT_LINK_ACTIONS]
    blocked = [r for r in records if not r["policy_allowed"]]

    amount_total = sum(r["amount"] for r in records)
    amount_in_recovery_flow = sum(r["amount"] for r in recovery_initiated)

    by_reason = defaultdict(lambda: {"total": 0, "action_taken": 0, "amount_total": 0.0, "amount_recovered_flow": 0.0})
    for r in records:
        reason = r["failure_reason"]
        by_reason[reason]["total"] += 1
        by_reason[reason]["amount_total"] += r["amount"]
        if r["action_taken"] in PAYMENT_LINK_ACTIONS:
            by_reason[reason]["action_taken"] += 1
            by_reason[reason]["amount_recovered_flow"] += r["amount"]

    by_category = defaultdict(int)
    for r in records:
        by_category[r["root_cause_category"]] += 1

    return {
        "total_transactions": total,
        "recovery_actions_initiated": len(recovery_initiated),
        "blocked_by_policy": len(blocked),
        "amount_total": round(amount_total, 2),
        "amount_in_recovery_flow": round(amount_in_recovery_flow, 2),
        "recovery_initiation_rate_pct": round(len(recovery_initiated) / total * 100, 1),
        "by_failure_reason": dict(by_reason),
        "by_root_cause_category": dict(by_category),
    }


def blocked_breakdown(records: list[dict]) -> dict:
    """Why things got blocked — proves the compliance/policy logic to judges."""
    reasons = defaultdict(int)
    for r in records:
        if not r["policy_allowed"]:
            reason_text = r["policy_reason"]
            if "compliance or requires customer action" in reason_text:
                key = "Compliance / needs customer action"
            elif "MAX_RETRIES_PER_TRANSACTION" in reason_text:
                key = "Max retries exceeded"
            elif "MAX_RECOVERY_WINDOW_DAYS" in reason_text:
                key = "Recovery window expired"
            elif "cooldown requires" in reason_text:
                key = "Cooldown not yet met"
            elif "not retryable" in reason_text:
                key = "Diagnosis marked non-retryable"
            else:
                key = "Other"
            reasons[key] += 1
    return dict(reasons)


if __name__ == "__main__":
    records = load_audit_trail()
    summary = compute_summary(records)
    print(json.dumps(summary, indent=2))
    print("\nBlocked breakdown:")
    print(json.dumps(blocked_breakdown(records), indent=2))
