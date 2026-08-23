from app.extensions import db


def lock_for_update(query):
    """
    SELECT ... FOR UPDATE where the dialect supports it (Postgres/MySQL — what
    production runs on). Plain SELECT on SQLite, which has no row-level locking
    at all and is only ever used here for local smoke tests.

    Shared by app/services/seat_service.py and app/services/waitlist_service.py —
    every read-then-write of a seat_status or waitlist row goes through this.
    """
    if db.engine.dialect.name in ("postgresql", "mysql", "mariadb"):
        return query.with_for_update()
    return query
