# Failed Payment Recovery Agent

**Razorpay AI Buildathon 2026 — Track 3: AI Revenue Recovery**

An agent that diagnoses *why* a payment failed, decides whether and how
to recover it under strict compliance rules, executes the recovery
action via Razorpay, and reports honest, measured recovery numbers.

> Detailed pipeline design and reasoning: see [ARCHITECTURE.md](ARCHITECTURE.md)

## What it does

1. Reads a batch of failed transactions
2. **Diagnoses** the root cause of each failure using a rules engine
   based on real Razorpay failure codes
3. **Checks policy** — hard-blocks fraud/compliance cases, caps retries,
   enforces a 7-day recovery window and per-category cooldowns
4. **Executes** the recovery action (creates a Razorpay test-mode
   payment link, or falls back to a mock client)
5. **Logs** every decision to an audit trail
6. **Reports** recovery rate, ₹ recovered, and blocked-case breakdown on
   a Streamlit dashboard

## Project structure

```
├── data/
│   ├── generate_dataset.py    # synthetic failed-transaction generator
│   ├── failed_transactions.csv
│   └── failure_codes.md       # research notes on real Razorpay failure codes
├── src/
│   ├── diagnosis.py           # root-cause rules engine
│   ├── retry_policy.py        # compliance / stopping rules
│   ├── razorpay_client.py     # Razorpay test-mode API wrapper + mock
│   └── recovery_agent.py      # orchestration loop
├── dashboard/
│   ├── metrics.py             # computes summary stats from audit trail
│   └── app.py                 # Streamlit dashboard
├── logs/
│   └── audit_trail.jsonl      # every decision + action + outcome
├── tests/
│   └── test_diagnosis.py      # unit tests for diagnosis + policy
├── requirements.txt
└── .env.example
```

## Setup

```bash
# 1. Clone and enter the repo
git clone <your-repo-url>
cd failed-payment-recovery-agent

# 2. Create a virtual environment
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add your Razorpay test-mode keys (optional — mock fallback works without this)
cp .env.example .env
# edit .env and fill in RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET (must start with rzp_test_)
```

## Running the pipeline

```bash
# Generate a fresh synthetic dataset
cd data
python3 generate_dataset.py --rows 200 --seed 42

# Run the recovery agent over the batch (mock client, safe/offline)
cd ../src
python3 recovery_agent.py

# Run unit tests
cd ..
python3 -m pytest tests/ -v

# Launch the dashboard
cd dashboard
streamlit run app.py
```

To run against the real Razorpay test-mode API instead of the mock,
edit the `use_mock=True` flag in `src/recovery_agent.py`'s `__main__`
block (or call `run_batch(..., use_mock=False)` directly). Only
`rzp_test_` keys are accepted — the client refuses to run with a live
key.

## Sample results (200-transaction synthetic batch)

| Metric | Value |
|---|---|
| Total transactions | 200 |
| Recovery actions initiated | ~145 |
| Blocked by policy | ~55 |
| ₹ moved into recovery flow | ~₹18.6L |

Blocked cases break down into: fraud/compliance blocks, cooldown not yet
met, and recovery-window expiry — see the dashboard's "Why Transactions
Were Blocked" panel for the live breakdown on any given run.

## Live dashboard

https://failed-payment-recovery-agent.streamlit.app/

## Notes for reviewers

- All transaction data is synthetic — no real customer data is used.
- Failure-reason categories and their recovery strategy are grounded in
  Razorpay's own documented error/decline codes (see
  `data/failure_codes.md` for sources).
- The compliance layer (`src/retry_policy.py`) is unit-tested
  (`tests/test_diagnosis.py`) specifically on the cases that matter most
  — fraud is never auto-retried, retries stop after the recovery window,
  and cooldowns are enforced.
