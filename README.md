# Subscription Sniper

A six-hour hackathon MVP that analyzes a bank statement CSV and detects likely recurring subscription payments.

## Features
- CSV upload with selectable date, description, and amount columns
- Merchant-name normalization using editable keyword rules
- Rule-based recurring interval detection (weekly, monthly, quarterly, yearly)
- Monthly/yearly estimated costs and Plotly chart
- Predicted renewals in the next seven days
- Price-hike flags, savings suggestions, and possible overlapping services
- User correction: exclude a false-positive merchant and recalculate totals
- Download renewal calendar as `.ics`

## Run locally

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

Then upload `sample_statement.csv` in the sidebar.

## Team split
- Person 1: `engine.py` — data cleaning, merchant normalization, recurrence detection, cost estimates, renewal logic, suggestions, calendar export.
- Person 2: `app.py` — Streamlit interface, charts, upload/column mapping, alerts, correction control, and download button.

## Suggested Git workflow
Create the repository at the event's announced start time. Work on separate branches if comfortable, or split ownership by file. Commit small working milestones regularly and push before the event deadline.

## Important limitations
- This is a demo prototype, not financial advice.
- Merchant aliases are rule-based and must be expanded for unfamiliar merchants.
- The recurrence detector requires at least two transactions and can produce false positives.
- Renewal dates are estimates based on the last observed payment and inferred interval.
- Potential duplicate services are only category-level hints; they do not prove that a user has redundant subscriptions.
- Use sample or redacted statements for public demos. Do not commit real bank statements to GitHub.
