from datetime import datetime, timezone


def parse_iso_datetime(value):
    """ISO 8601 string -> naive UTC datetime, or None if missing/unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_date(value):
    """'YYYY-MM-DD' string -> date, or None if missing/unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
