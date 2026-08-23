"""
Background scheduler for all time-based expiry:
  - releasing expired seat holds back to 'available'
  - expiring stale waitlist offers and cascading to the next in line

The actual sweep logic lives in app/services (added in the seat/waitlist phase);
this module just wires APScheduler to call them on an interval, inside an app context.
"""
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler(daemon=True)


def init_scheduler(app):
    interval = app.config["SCHEDULER_INTERVAL_SECONDS"]

    def sweep():
        with app.app_context():
            # Imported lazily so the module can load before services exist.
            try:
                from app.services.seat_service import release_expired_holds
                release_expired_holds()
            except ImportError:
                pass
            try:
                from app.services.waitlist_service import expire_stale_offers
                expire_stale_offers()
            except ImportError:
                pass

    scheduler.add_job(
        sweep,
        "interval",
        seconds=interval,
        id="expiry_sweep",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if not scheduler.running:
        scheduler.start()
    app.logger.info("Scheduler started; expiry sweep every %ss", interval)
