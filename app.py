"""Streamlit UI for Subscription Sniper."""
import pandas as pd
import plotly.express as px
import streamlit as st

from engine import (
    detect_subscriptions,
    export_calendar,
    make_savings_suggestions,
    prepare_transactions,
    upcoming_renewals,
)

st.set_page_config(page_title="Subscription Sniper", page_icon="🎯", layout="wide")
st.title("🎯 Subscription Sniper")
st.caption("Find recurring payments, spot price increases, and understand your subscription spending.")

with st.sidebar:
    st.header("Upload statement")
    uploaded = st.file_uploader("Choose a bank statement CSV", type=["csv"])
    st.caption("Privacy tip: use a sample or redacted statement for demos. This prototype processes data in the app session.")

    with st.expander("CSV format example"):
        st.code("Date,Description,Amount\n2026-01-05,NETFLIX.COM 8847,-199\n2026-02-05,Netflix IN,-199\n2026-03-06,Netflix*Sub,-249", language="csv")

if uploaded is None:
    st.info("Upload a CSV to begin. Your file should include a transaction date, description, and amount column.")
    st.subheader("What you'll get")
    st.write("- Recurring subscription detection")
    st.write("- Monthly and annual cost estimates")
    st.write("- Upcoming renewals and price-hike alerts")
    st.write("- Savings suggestions and calendar export")
    st.stop()

try:
    raw = pd.read_csv(uploaded)
except Exception as exc:
    st.error(f"Could not read this CSV: {exc}")
    st.stop()

st.subheader("Map your CSV columns")
columns = list(raw.columns)
if len(columns) < 3:
    st.error("The CSV needs at least three columns: date, description, and amount.")
    st.stop()

def guess_col(options, keywords, fallback_index):
    for col in options:
        if any(word in str(col).lower() for word in keywords):
            return col
    return options[min(fallback_index, len(options) - 1)]

c1, c2, c3 = st.columns(3)
with c1:
    date_col = st.selectbox("Date column", columns, index=columns.index(guess_col(columns, ["date", "txn", "time"], 0)))
with c2:
    description_col = st.selectbox("Description / merchant column", columns, index=columns.index(guess_col(columns, ["description", "merchant", "narration", "details", "particular"], 1)))
with c3:
    amount_col = st.selectbox("Amount column", columns, index=columns.index(guess_col(columns, ["amount", "debit", "withdrawal", "value"], 2)))

transactions = prepare_transactions(raw, date_col, description_col, amount_col)
if transactions.empty:
    st.error("No valid transactions found. Check the selected columns and date/amount format.")
    st.stop()

subscriptions = detect_subscriptions(transactions)
if subscriptions.empty:
    st.warning("No recurring subscriptions detected yet. Detection generally needs at least two payments from the same normalized merchant at a regular interval.")
    with st.expander("Preview cleaned transactions"):
        st.dataframe(transactions, use_container_width=True)
    st.stop()

# Persist user corrections for this browser session. Recalculate visible results after exclusions.
if "excluded_merchants" not in st.session_state:
    st.session_state.excluded_merchants = set()

all_detected = subscriptions.copy()
subscriptions = subscriptions[~subscriptions["merchant"].isin(st.session_state.excluded_merchants)].copy()

monthly_total = float(subscriptions["monthly_cost"].sum()) if not subscriptions.empty else 0.0
yearly_total = float(subscriptions["yearly_cost"].sum()) if not subscriptions.empty else 0.0

k1, k2, k3, k4 = st.columns(4)
k1.metric("Detected subscriptions", len(subscriptions))
k2.metric("Estimated monthly cost", f"₹{monthly_total:,.2f}")
k3.metric("Estimated yearly cost", f"₹{yearly_total:,.2f}")
k4.metric("Price hikes", int(subscriptions["price_hike"].sum()) if not subscriptions.empty else 0)

st.divider()
left, right = st.columns([1.25, 1])
with left:
    st.subheader("Subscription breakdown")
    if not subscriptions.empty:
        chart = px.bar(
            subscriptions.sort_values("yearly_cost", ascending=True),
            x="yearly_cost", y="merchant", orientation="h",
            labels={"yearly_cost": "Estimated yearly cost (₹)", "merchant": "Subscription"},
            title="Estimated yearly cost by subscription",
        )
        st.plotly_chart(chart, use_container_width=True)
    else:
        st.info("All detected subscriptions have been excluded from the totals.")

with right:
    st.subheader("Renewing in the next 7 days")
    upcoming = upcoming_renewals(subscriptions, days=7)
    if upcoming.empty:
        st.write("No predicted renewals in the next 7 days.")
    else:
        st.dataframe(
            upcoming[["merchant", "next_renewal", "latest_amount", "frequency"]]
            .rename(columns={"merchant": "Subscription", "next_renewal": "Expected date",
                             "latest_amount": "Latest charge (₹)", "frequency": "Frequency"}),
            use_container_width=True, hide_index=True,
        )

st.subheader("Detected subscriptions")
display_cols = ["merchant", "category", "frequency", "payments_found", "latest_amount",
                "monthly_cost", "yearly_cost", "last_payment", "next_renewal", "price_hike"]
display = subscriptions[display_cols].rename(columns={
    "merchant": "Merchant", "category": "Category", "frequency": "Frequency",
    "payments_found": "Payments", "latest_amount": "Latest charge (₹)",
    "monthly_cost": "Monthly estimate (₹)", "yearly_cost": "Yearly estimate (₹)",
    "last_payment": "Last payment", "next_renewal": "Predicted renewal",
    "price_hike": "Price hike?",
})
st.dataframe(display, use_container_width=True, hide_index=True)

hikes = subscriptions[subscriptions["price_hike"]] if not subscriptions.empty else subscriptions
if not hikes.empty:
    st.subheader("⚠️ Price-hike alerts")
    for _, row in hikes.iterrows():
        change = row["latest_amount"] - row["previous_amount"]
        st.warning(
            f"{row['merchant']}: ₹{row['previous_amount']:.2f} → ₹{row['latest_amount']:.2f} "
            f"(increase of ₹{change:.2f}). Verify that this is a real price change."
        )

st.subheader("💡 Savings suggestions")
suggestions = make_savings_suggestions(subscriptions)
if suggestions.empty:
    st.write("No suggestions available.")
else:
    st.dataframe(
        suggestions.rename(columns={"merchant": "Subscription(s)", "suggestion": "Suggestion",
                                    "potential_yearly_saving": "Potential annual saving (₹)"}),
        use_container_width=True, hide_index=True,
    )

st.subheader("Correct the detection")
if not all_detected.empty:
    options = [m for m in all_detected["merchant"].tolist() if m not in st.session_state.excluded_merchants]
    if options:
        selected = st.selectbox("Choose an item that is not a subscription", options)
        if st.button("Mark as not a subscription"):
            st.session_state.excluded_merchants.add(selected)
            st.rerun()
    else:
        st.success("All detected items have been excluded.")

st.subheader("📅 Export renewal calendar")
calendar_text = export_calendar(subscriptions)
st.download_button(
    "Download renewals (.ics)",
    data=calendar_text,
    file_name="subscription_renewals.ics",
    mime="text/calendar",
    disabled=subscriptions.empty,
)

with st.expander("Show cleaned transactions"):
    st.dataframe(transactions, use_container_width=True, hide_index=True)

st.caption("Prototype note: detection is rule-based and may miss unfamiliar merchant names or irregular billing. Renewal dates are estimates, not guarantees.")
