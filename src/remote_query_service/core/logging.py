from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from remote_query_service.core.settings import Settings

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_LOGGER_NAMES = ("", "uvicorn", "uvicorn.error")


def _has_file_handler(logger: logging.Logger, path: Path) -> bool:
    resolved = path.resolve()
    for handler in logger.handlers:
        base_filename = getattr(handler, "baseFilename", None)
        if base_filename and Path(base_filename).resolve() == resolved:
            return True
    return False


def _attach_error_file_handler(logger: logging.Logger, path: Path) -> None:
    if _has_file_handler(logger, path):
        return
    handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setLevel(logging.ERROR)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(handler)


def configure_error_logging(settings: Settings) -> None:
    if not settings.error_log_path:
        return
    path = settings.error_log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    for logger_name in _LOGGER_NAMES:
        logger = logging.getLogger(logger_name)
        _attach_error_file_handler(logger, path)
