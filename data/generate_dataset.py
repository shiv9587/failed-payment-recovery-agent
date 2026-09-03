"""
Generates a synthetic batch of failed payment transactions for the
Failed Payment Recovery Agent (Razorpay AI Buildathon - Track 3).

Failure reason codes are based on real Razorpay documentation
(see failure_codes.md in this folder) with a realistic distribution:
most failures are recoverable (insufficient funds, OTP, network),
a smaller share are compliance-blocked (fraud, wrong account).

Usage:
    python generate_dataset.py --rows 200 --seed 42
"""

import argparse
import csv
import random
import uuid
from datetime import datetime, timedelta

# reason_code: (weight, source, payment_method_pool)
FAILURE_PROFILES = {
    "insufficient_funds":      (22, "customer", ["card", "upi"]),
    "incorrect_otp":           (12, "customer", ["card"]),
    "card_declined_by_bank":   (14, "bank",     ["card"]),
    "card_not_enabled_online": (5,  "customer", ["card"]),
    "fraud_suspected":         (4,  "bank",     ["card"]),
    "upi_collect_expired":     (15, "customer", ["upi"]),
    "upi_bank_downtime":       (10, "bank",     ["upi"]),
    "upi_wrong_bank_account":  (4,  "customer", ["upi"]),
    "network_error":           (9,  "gateway",  ["card", "upi", "netbanking"]),
    "customer_cancelled":      (8,  "customer", ["card", "upi", "netbanking"]),
    "card_expired":            (7,  "customer", ["card"]),
}

CUSTOMER_POOL_SIZE = 120  # some customers appear more than once (repeat failures)


def weighted_choice(profiles):
    reasons = list(profiles.keys())
    weights = [profiles[r][0] for r in reasons]
    return random.choices(reasons, weights=weights, k=1)[0]


def generate_row(customer_ids, base_time):
    reason = weighted_choice(FAILURE_PROFILES)
    _, source, method_pool = FAILURE_PROFILES[reason]
    method = random.choice(method_pool)

    amount = round(random.uniform(149, 24999), 2)
    customer_id = random.choice(customer_ids)
    txn_time = base_time - timedelta(
        days=random.randint(0, 6),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )

    return {
        "transaction_id": f"txn_{uuid.uuid4().hex[:14]}",
        "customer_id": customer_id,
        "amount": amount,
        "payment_method": method,
        "failure_reason": reason,
        "failure_source": source,
        "attempt_number": 1,
        "timestamp": txn_time.isoformat(timespec="seconds"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default="failed_transactions.csv")
    args = parser.parse_args()

    random.seed(args.seed)
    customer_ids = [f"cust_{uuid.uuid4().hex[:8]}" for _ in range(CUSTOMER_POOL_SIZE)]
    base_time = datetime.now()

    rows = [generate_row(customer_ids, base_time) for _ in range(args.rows)]
    rows.sort(key=lambda r: r["timestamp"])

    fieldnames = list(rows[0].keys())
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} rows -> {args.out}")
    # quick distribution summary
    from collections import Counter
    counts = Counter(r["failure_reason"] for r in rows)
    for reason, count in counts.most_common():
        print(f"  {reason:<25} {count:>4}  ({count/len(rows)*100:.1f}%)")


if __name__ == "__main__":
    main()
