"""Period boundaries the PostgreSQL SQL computed with date_trunc(), in UTC."""

import datetime as dt

_UTC = dt.timezone.utc


def start_of_week():
    """date_trunc('week', now()): Monday 00:00 UTC."""
    today = dt.datetime.now(_UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - dt.timedelta(days=today.weekday())


def start_of_month():
    """date_trunc('month', now()): the 1st at 00:00 UTC."""
    return dt.datetime.now(_UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def days_ago(days):
    return dt.datetime.now(_UTC) - dt.timedelta(days=days)
