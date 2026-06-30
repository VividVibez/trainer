"""
Week / date maths for the planner — pure functions, no DB access, so they're
easy to test in isolation. The blueprint reads `plan_start_date` from settings
and passes it in.

Plan weeks anchor to Monday: week 1 starts on the Monday of the week containing
the plan start date, so the Mon–Sun strip always lines up with real weekdays.
"""
import datetime

TOTAL_WEEKS = 52

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]          # index by date.weekday()
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]              # index by month-1


def ordinal(n):
    """1 -> '1st', 2 -> '2nd', 3 -> '3rd', 4 -> '4th', 21 -> '21st' ..."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th', 'st', 'nd', 'rd', 'th', 'th', 'th', 'th', 'th', 'th'][n % 10]}"


def parse_start(value):
    """Parse an ISO date string from settings; fall back to today if missing/bad."""
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.date.today()


def anchor_monday(start):
    """Monday of the week containing the plan start date."""
    return start - datetime.timedelta(days=start.weekday())


def days_until_start(start, today=None):
    """Positive days until the plan's first Monday; 0 once the plan has started."""
    today = today or datetime.date.today()
    return max(0, (anchor_monday(start) - today).days)


def current_week_number(start, today=None, total=TOTAL_WEEKS):
    """Which plan week 'today' falls in, clamped to 1..total (the active plan's
    length; defaults to 52 for callers that don't pass one)."""
    today = today or datetime.date.today()
    delta_days = (today - anchor_monday(start)).days
    wk = delta_days // 7 + 1
    return max(1, min(total, wk))


def week_monday(start, n):
    """Monday date for plan week n."""
    return anchor_monday(start) + datetime.timedelta(weeks=n - 1)


def week_days(start, n, today=None):
    """List of 7 day dicts (Mon..Sun) for week n, each with a dated label."""
    today = today or datetime.date.today()
    mon = week_monday(start, n)
    out = []
    for i in range(7):
        d = mon + datetime.timedelta(days=i)
        out.append({
            "index": i + 1,                                   # 1..7 (matches day_assignment.day_index)
            "dow": DOW[d.weekday()],
            "label": f"{DOW[d.weekday()]} {ordinal(d.day)} {MONTHS[d.month - 1]}",
            "day_num": d.day,
            "month": MONTHS[d.month - 1],
            "iso": d.isoformat(),
            "is_today": d == today,
        })
    return out


def week_range_label(start, n):
    """Compact date range for the header, e.g. '15–21 Jun' or '29 Jun – 5 Jul'."""
    mon = week_monday(start, n)
    sun = mon + datetime.timedelta(days=6)
    if mon.month == sun.month:
        return f"{mon.day}–{sun.day} {MONTHS[mon.month - 1]}"
    return f"{mon.day} {MONTHS[mon.month - 1]} – {sun.day} {MONTHS[sun.month - 1]}"
