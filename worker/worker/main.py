import logging
import sys

from worker.config import get_settings
from worker.inventory import ingest_inventory


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
    raise SystemExit(f"unknown command {sys.argv[1]}")


if __name__ == "__main__":
    main()
