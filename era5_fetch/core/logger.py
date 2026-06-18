from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from era5_fetch.core.config import Config


def configure_logging(config: Config) -> logging.Logger:
    config.ensure_directories()
    logger = logging.getLogger("era5_fetch")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
    )
    file_handler = RotatingFileHandler(
        config.logs_dir / "era5_fetch.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger
