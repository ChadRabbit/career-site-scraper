import logging
from datetime import datetime

from scraper import settings

LOGGER_NAME = "job_scraper"


def setup_logger(level=logging.INFO, to_file=True) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    if to_file:
        settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(settings.LOG_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.log")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
