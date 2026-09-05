"""
Streamlit dashboard — Failed Payment Recovery Agent (Track 3).

Run with:
    streamlit run app.py

Shows:
    - Headline metrics (recovery rate, amount in recovery flow)
    - Breakdown by failure reason (recoverable vs blocked)
    - Why transactions got blocked (proves compliance logic works)
    - Full audit trail table (searchable/filterable)
"""

import sys
import os
import json

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
from metrics import load_audit_trail, compute_summary, blocked_breakdown

st.set_page_config(page_title="Failed Payment Recovery Agent", layout="wide")

st.title("💳 Failed Payment Recovery Agent")
st.caption("Razorpay AI Buildathon — Track 3: AI Revenue Recovery")

records = load_audit_trail()

if not records:
    st.warning(
        "No audit trail found yet. Run `python3 src/recovery_agent.py` "
        "first to generate `logs/audit_trail.jsonl`."
    )
    st.stop()

summary = compute_summary(records)
blocked = blocked_breakdown(records)

# ---- Headline metrics ----
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Transactions", summary["total_transactions"])
col2.metric("Recovery Actions Initiated", summary["recovery_actions_initiated"],
            f"{summary['recovery_initiation_rate_pct']}%")
col3.metric("₹ In Recovery Flow", f"₹{summary['amount_in_recovery_flow']:,.0f}")
col4.metric("Blocked by Policy", summary["blocked_by_policy"])

st.divider()

# ---- Breakdown by failure reason ----
st.subheader("Breakdown by Failure Reason")
reason_df = pd.DataFrame([
    {
        "Failure Reason": reason,
        "Total": data["total"],
        "Action Taken": data["action_taken"],
        "Blocked": data["total"] - data["action_taken"],
        "Amount Total (₹)": round(data["amount_total"], 2),
        "Amount in Recovery Flow (₹)": round(data["amount_recovered_flow"], 2),
    }
    for reason, data in summary["by_failure_reason"].items()
]).sort_values("Total", ascending=False)

st.dataframe(reason_df, use_container_width=True, hide_index=True)

left, right = st.columns(2)
with left:
    st.bar_chart(reason_df.set_index("Failure Reason")[["Action Taken", "Blocked"]])
with right:
    cat_df = pd.DataFrame([
        {"Root Cause Category": k, "Count": v}
        for k, v in summary["by_root_cause_category"].items()
    ])
    if not cat_df.empty and "Root Cause Category" in cat_df.columns:
        st.bar_chart(cat_df.set_index("Root Cause Category"))

st.divider()

# ---- Why things got blocked (compliance proof) ----
st.subheader("Why Transactions Were Blocked")
st.caption(
    "This is the compliance layer working as intended — e.g. fraud-suspected "
    "transactions are never auto-retried, retries stop after the recovery "
    "window, and cooldowns prevent spamming the customer."
)

if blocked:
    blocked_df = pd.DataFrame([
        {"Block Reason": k, "Count": v} for k, v in blocked.items()
    ])
    if "Count" in blocked_df.columns:
        blocked_df = blocked_df.sort_values("Count", ascending=False)
    st.dataframe(blocked_df, use_container_width=True, hide_index=True)
else:
    st.success("✅ **0 Transactions Blocked:** All transactions in this batch were successfully processed through recovery policy!")

st.divider()

# ---- Full audit trail ----
st.subheader("Full Audit Trail")
audit_df = pd.DataFrame(records)

# expand action_result dict into a readable column
audit_df["action_result_short"] = audit_df["action_result"].apply(
    lambda r: r.get("short_url", r.get("note", "")) if isinstance(r, dict) and r is not None else ""
)

display_cols = [
    "transaction_id", "customer_id", "amount", "payment_method",
    "failure_reason", "root_cause_category", "recommended_action",
    "policy_allowed", "action_taken", "action_result_short", "processed_at",
]

# Ensure display_cols exist before showing
existing_cols = [col for col in display_cols if col in audit_df.columns]
st.dataframe(audit_df[existing_cols], use_container_width=True, hide_index=True)

st.download_button(
    "Download audit trail as CSV",
    audit_df[existing_cols].to_csv(index=False),
    file_name="audit_trail_export.csv",
    mime="text/csv",
)