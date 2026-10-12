import logging
import sys

from worker.billing_ingest import ingest_billing
from worker.config import get_settings
from worker.inventory import ingest_inventory
from worker.metric_ingest import ingest_metrics


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    get_settings()
    logging.info("worker ok")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) == 1:
        run()
        return
    if sys.argv[1:] == ["ingest-inventory"]:
        counts = ingest_inventory()
        logging.info(
            "inventory ingest created=%s updated=%s total=%s",
            counts.created,
            counts.updated,
            counts.total,
        )
        return
    if sys.argv[1:] == ["ingest-metrics"]:
        counts = ingest_metrics()
        logging.info(
            "metrics ingest created=%s updated=%s rollups=%s resources=%s",
            counts.created,
            counts.updated,
            counts.rollups,
            counts.resources_with_series,
        )
        return
    if sys.argv[1:] == ["ingest-billing"]:
        counts = ingest_billing()
        logging.info(
            "billing ingest created=%s updated=%s records=%s",
            counts.created,
            counts.updated,
            counts.records,
        )
        return
    raise SystemExit(f"unknown command {sys.argv[1]}")


if __name__ == "__main__":
    main()
