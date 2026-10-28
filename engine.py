"""Core transaction cleaning and subscription-detection logic for Subscription Sniper."""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Optional

import pandas as pd

# Demo-friendly merchant aliases. Extend these as needed during the hackathon.
MERCHANT_RULES = [
    (r"netflix", "Netflix", "OTT"),
    (r"spotify", "Spotify", "Music"),
    (r"youtube\s*premium|google\s*youtube", "YouTube Premium", "Video/Music"),
    (r"prime\s*video|amazon\s*prime", "Amazon Prime", "OTT"),
    (r"disney|hotstar", "Disney+ Hotstar", "OTT"),
    (r"jio\s*hotstar", "JioHotstar", "OTT"),
    (r"apple\s*music", "Apple Music", "Music"),
    (r"gaana", "Gaana", "Music"),
    (r"icloud|apple\s*storage", "iCloud", "Cloud storage"),
    (r"google\s*one|google\s*storage", "Google One", "Cloud storage"),
    (r"adobe", "Adobe", "Software"),
    (r"microsoft\s*365|office\s*365", "Microsoft 365", "Software"),
    (r"gym|fitness\s*club", "Gym membership", "Fitness"),
]

# Typical intervals, in days. We allow calendar-month drift.
FREQUENCIES = {
    "weekly": 7,
    "monthly": 30,
    "quarterly": 91,
    "yearly": 365,
}


def normalize_merchant(description: str) -> tuple[str, str]:
    """Return a normalized merchant and category using simple keyword rules."""
    raw = str(description or "").lower()
    raw = re.sub(r"\b\d{3,}\b", " ", raw)
    raw = re.sub(r"[^a-z0-9\s*]", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()

    for pattern, merchant, category in MERCHANT_RULES:
        if re.search(pattern, raw, flags=re.I):
            return merchant, category

    # Conservative fallback: use the first few cleaned words.
    words = raw.split()
    merchant = " ".join(words[:3]).title() if words else "Unknown merchant"
    return merchant, "Other"


def infer_frequency(dates: pd.Series) -> tuple[Optional[str], list[int]]:
    """Infer a regular payment interval from sorted dates; returns frequency and gaps."""
    parsed = pd.to_datetime(dates, errors="coerce").dropna().sort_values()
    if len(parsed) < 2:
        return None, []

    gaps = parsed.diff().dropna().dt.days.astype(int).tolist()
    if not gaps:
        return None, []

    # Median is robust to a single shifted payment date.
    median_gap = float(pd.Series(gaps).median())
    candidates = sorted(FREQUENCIES.items(), key=lambda item: abs(median_gap - item[1]))
    name, expected = candidates[0]

    # Require a reasonable range around the expected interval.
    tolerance = max(4, int(expected * 0.18))
    if abs(median_gap - expected) > tolerance:
        return None, gaps

    # Most gaps should be close to the selected interval.
    close = sum(abs(gap - expected) <= max(5, int(expected * 0.22)) for gap in gaps)
    if close / len(gaps) < 0.60:
        return None, gaps

    return name, gaps


def prepare_transactions(
    df: pd.DataFrame,
    date_col: str,
    description_col: str,
    amount_col: str,
) -> pd.DataFrame:
    """Clean a user-uploaded statement into a consistent transaction table."""
    result = df[[date_col, description_col, amount_col]].copy()
    result.columns = ["date", "description", "amount"]
    result["date"] = pd.to_datetime(result["date"], errors="coerce", dayfirst=True)
    result["amount"] = (
        result["amount"].astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("₹", "", regex=False)
        .str.replace("INR", "", regex=False)
        .str.strip()
    )
    result["amount"] = pd.to_numeric(result["amount"], errors="coerce")
    result["description"] = result["description"].astype(str)
    result = result.dropna(subset=["date", "amount"])
    result = result[result["amount"] != 0].copy()

    normalized = result["description"].apply(normalize_merchant)
    result["merchant"] = normalized.apply(lambda x: x[0])
    result["category"] = normalized.apply(lambda x: x[1])

    # Use absolute value for costs, since some statements store debits as negatives.
    result["amount"] = result["amount"].abs()
    return result.sort_values("date").reset_index(drop=True)


def detect_subscriptions(transactions: pd.DataFrame) -> pd.DataFrame:
    """Find merchants with recurring intervals and summarize cost/price changes."""
    rows = []
    for merchant, group in transactions.groupby("merchant"):
        group = group.sort_values("date")
        if len(group) < 2:
            continue

        frequency, gaps = infer_frequency(group["date"])
        if not frequency:
            continue

        amounts = group["amount"].astype(float)
        latest_amount = float(amounts.iloc[-1])
        previous_amount = float(amounts.iloc[-2])
        price_hike = latest_amount > previous_amount * 1.05
        avg_amount = float(amounts.median())

        monthly_multiplier = {
            "weekly": 52 / 12,
            "monthly": 1,
            "quarterly": 1 / 3,
            "yearly": 1 / 12,
        }[frequency]

        last_date = pd.Timestamp(group["date"].iloc[-1])
        next_date = last_date + pd.Timedelta(days=FREQUENCIES[frequency])

        rows.append({
            "merchant": merchant,
            "category": group["category"].mode().iloc[0],
            "frequency": frequency,
            "payments_found": len(group),
            "last_payment": last_date.date(),
            "next_renewal": next_date.date(),
            "latest_amount": round(latest_amount, 2),
            "previous_amount": round(previous_amount, 2),
            "price_hike": bool(price_hike),
            "monthly_cost": round(avg_amount * monthly_multiplier, 2),
            "yearly_cost": round(avg_amount * monthly_multiplier * 12, 2),
        })

    return pd.DataFrame(rows).sort_values("yearly_cost", ascending=False).reset_index(drop=True) if rows else pd.DataFrame(
        columns=["merchant", "category", "frequency", "payments_found", "last_payment",
                 "next_renewal", "latest_amount", "previous_amount", "price_hike",
                 "monthly_cost", "yearly_cost"]
    )


def upcoming_renewals(subscriptions: pd.DataFrame, today=None, days: int = 7) -> pd.DataFrame:
    if subscriptions.empty:
        return subscriptions.copy()
    today = pd.Timestamp(today or pd.Timestamp.today().date()).date()
    end = today + timedelta(days=days)
    dates = pd.to_datetime(subscriptions["next_renewal"], errors="coerce").dt.date
    mask = dates.between(today, end)
    return subscriptions.loc[mask].copy().sort_values("next_renewal")


def make_savings_suggestions(subscriptions: pd.DataFrame) -> pd.DataFrame:
    """Create transparent, rule-based savings hints; never automatically cancels anything."""
    if subscriptions.empty:
        return pd.DataFrame(columns=["merchant", "suggestion", "potential_yearly_saving"])

    output = []
    for _, row in subscriptions.iterrows():
        output.append({
            "merchant": row["merchant"],
            "suggestion": f"Review whether you still use {row['merchant']}.",
            "potential_yearly_saving": row["yearly_cost"],
        })

    # Flag categories with multiple detected subscriptions as possible overlap, not certainty.
    for category, group in subscriptions.groupby("category"):
        if category in {"OTT", "Music", "Video/Music"} and len(group) > 1:
            names = ", ".join(group["merchant"].astype(str).tolist())
            output.append({
                "merchant": names,
                "suggestion": f"Possible overlapping services in {category}; review whether you need all of them.",
                "potential_yearly_saving": 0.0,
            })

    return pd.DataFrame(output)


def export_calendar(subscriptions: pd.DataFrame) -> str:
    """Create a basic iCalendar file for upcoming renewal dates."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Subscription Sniper//EN",
        "CALSCALE:GREGORIAN",
    ]
    for _, row in subscriptions.iterrows():
        date = pd.to_datetime(row["next_renewal"], errors="coerce")
        if pd.isna(date):
            continue
        date_text = date.strftime("%Y%m%d")
        title = str(row["merchant"]).replace(",", r"\,").replace(";", r"\;")
        amount = float(row["latest_amount"])
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{re.sub(r'[^a-zA-Z0-9]', '', title)}-{date_text}@subscriptionsniper",
            f"DTSTART;VALUE=DATE:{date_text}",
            f"SUMMARY:Renewal: {title}",
            f"DESCRIPTION:Expected charge INR {amount:.2f}. Verify with your provider.",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
