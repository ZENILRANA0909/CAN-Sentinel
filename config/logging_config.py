import logging
from logging.handlers import RotatingFileHandler

from config.settings import LOG_DIR


LOG_FILE = LOG_DIR / "application.log"


def configure_logging() -> None:
    """
    Configure application-wide logging.

    Logs are written to both:
    - Console
    - Rotating log file
    """

    root_logger = logging.getLogger()

    # Prevent duplicate handlers if called more than once.
    if root_logger.handlers:
        return

    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )

    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()

    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
