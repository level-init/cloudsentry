import logging

from worker.config import get_settings


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    get_settings()
    logging.info("worker ok")


if __name__ == "__main__":
    run()
