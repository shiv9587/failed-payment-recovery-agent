# Architecture — Failed Payment Recovery Agent

**Track 3: AI Revenue Recovery — Razorpay AI Buildathon 2026**

## Problem

Merchants lose real revenue to failed payments — insufficient funds, wrong
OTP, expired cards, bank downtime, suspected fraud. Most of these
failures are recoverable *if* you diagnose the actual root cause and
respond with the right action at the right time. Blind retries waste
money and annoy customers; no retries leave money on the table.

This agent detects a failed transaction, diagnoses *why* it failed,
decides whether and how to retry, executes the recovery action via
Razorpay, and logs every decision for audit.

## Pipeline Overview

```
                 ┌─────────────────────┐
                 │ failed_transactions  │   synthetic batch, modeled on
                 │        .csv          │   real Razorpay decline reasons
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │   diagnosis.py       │   rules engine:
                 │  (root cause engine) │   failure_reason -> root cause
                 └──────────┬───────────┘      category + recommended action
                            │
                            ▼
                 ┌─────────────────────┐
                 │  retry_policy.py     │   stopping rules:
                 │ (compliance gate)    │   - max 2 retries/txn
                 └──────────┬───────────┘   - 7-day recovery window
                            │               - per-category cooldowns
                     allowed?│              - hard block: fraud / needs
                       yes   │ no             customer action
                            ▼                       │
                 ┌─────────────────────┐             │
                 │ razorpay_client.py   │             │
                 │ (test-mode API /     │             │
                 │  mock fallback)      │             │
                 └──────────┬───────────┘             │
                            │                         │
                            ▼                         ▼
                 ┌─────────────────────────────────────┐
                 │   recovery_agent.py (orchestrator)   │
                 │   writes every decision + outcome    │
                 └──────────────────┬────────────────────┘
                                    │
                                    ▼
                 ┌─────────────────────┐
                 │ logs/audit_trail    │
                 │     .jsonl          │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ dashboard/app.py     │   Streamlit — recovery rate,
                 │  (Streamlit)         │   ₹ recovered, blocked reasons
                 └─────────────────────┘
```

## Why three separate layers (diagnosis / policy / execution)

These are kept as independent modules on purpose:

- **`diagnosis.py`** only answers *"what caused this failure, and what
  would help?"* It has no concept of retry limits or timing — that's a
  deliberate separation of concerns so the root-cause mapping can be
  audited and tested on its own.
- **`retry_policy.py`** only answers *"are we allowed to act right now?"*
  It layers hard compliance blocks, retry caps, a recovery window, and
  per-category cooldowns — independent of *what* the action is.
- **`razorpay_client.py`** only executes. It doesn't decide anything; it
  either calls the real Razorpay test-mode API or falls back to an
  in-memory mock with an identical interface, so a network hiccup or a
  missing API key never breaks the demo.

This separation means each layer can be unit-tested in isolation
(see `tests/test_diagnosis.py`) and the audit trail can show, for every
transaction, exactly *which layer* made which call — critical for a
financial-decisioning system.

## Rules engine over ML

Root-cause classification is a deterministic lookup table
(`DIAGNOSIS_RULES` in `diagnosis.py`), not a trained model. For a system
that moves money, an auditable, explainable rule ("insufficient_funds ->
retry after 48h, because balance is unlikely to refresh sooner") is more
defensible to a merchant, a compliance team, or a judge than a black-box
prediction. An unknown failure reason raises an error and routes to
manual review rather than being guessed at.

## Compliance-critical stopping rules

The policy layer enforces, regardless of what diagnosis recommends:

1. **Hard block** — `fraud_suspected` and any `NEEDS_CUSTOMER_ACTION`
   category (e.g. `card_expired`, `upi_wrong_bank_account`) are **never**
   auto-retried. These require a human or the customer, not an agent.
2. **Max retries** — capped at 2 attempts per transaction.
3. **Recovery window** — no action taken more than 7 days after the
   original failure.
4. **Cooldowns** — category-specific minimum gaps between attempts
   (e.g. 48h for insufficient-funds retries) so customers aren't spammed.

Every block records a human-readable reason, which is what powers the
"Why Transactions Were Blocked" panel on the dashboard.

## Data

`data/generate_dataset.py` produces a synthetic batch of failed
transactions using failure-reason categories and their real-world
distribution researched from Razorpay's own documentation on payment
error codes (see `data/failure_codes.md` for sources and reasoning).
No real customer or transaction data is used anywhere in this project.

## Execution layer / test-mode safety

`razorpay_client.py` refuses to run against anything other than a
`rzp_test_` key — it will raise rather than silently proceed if a live
key is detected. A `MockRazorpayClient` with an identical interface lets
the full 200-row batch run offline, deterministically, and without
hitting rate limits, and is also the safe fallback used during demos.

## Metrics & dashboard

`dashboard/metrics.py` computes recovery rate, amount moved into
recovery flow, and breakdowns by failure reason and root-cause category
directly from the audit trail — no numbers are hand-picked. The
dashboard (`dashboard/app.py`) is a Streamlit app reading the same
`logs/audit_trail.jsonl` file, so what's shown is exactly what the
agent actually decided and did on the batch it processed.

## What this project does *not* claim

- It does not attempt to recover `fraud_suspected` or
  `NEEDS_CUSTOMER_ACTION` cases — those are intentionally left blocked,
  and the honest recovery-rate numbers in the dashboard reflect that.
- "Recovery actions initiated" means a payment link / retry was
  triggered, not that the customer has necessarily completed payment —
  the pipeline includes payment-link status checks
  (`fetch_payment_link_status`) as the hook for closing that loop, but
  full reconciliation against actual completions is a natural next step
  beyond this submission's scope.
