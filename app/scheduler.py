import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import database
from . import crypto
from .collector import collect_and_parse, CollectionError

logger = logging.getLogger("juniper_monitor.scheduler")

scheduler = BackgroundScheduler()


def collect_one(switch_id: int):
    switch = database.get_switch(switch_id)
    if not switch:
        return
    creds = dict(switch)
    creds["password"] = crypto.decrypt(switch["password_enc"])
    try:
        summary, metrics, raw = collect_and_parse(creds)
        database.save_collection(switch_id, "success", summary, raw)
        database.save_metrics(switch_id, metrics)
        logger.info("Collected data for switch %s (%s)", switch["name"], switch["host"])
    except CollectionError as e:
        database.save_collection(switch_id, "error", {}, {}, error_message=str(e))
        logger.error("Collection failed for switch %s: %s", switch["name"], e)
    except Exception as e:
        database.save_collection(switch_id, "error", {}, {}, error_message=f"Unexpected error: {e}")
        logger.exception("Unexpected error collecting switch %s", switch["name"])


def collect_all():
    for switch in database.get_switches():
        collect_one(switch["id"])


def start(daily_hour: int = 2, daily_minute: int = 0):
    scheduler.add_job(
        collect_all,
        CronTrigger(hour=daily_hour, minute=daily_minute),
        id="daily_collection",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: daily collection at %02d:%02d", daily_hour, daily_minute)


def shutdown():
    scheduler.shutdown(wait=False)
