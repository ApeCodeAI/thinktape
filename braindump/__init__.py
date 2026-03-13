"""braindump — Personal expression material library."""

import logging

__version__ = "0.1.1"

# Configure root logger for braindump
logger = logging.getLogger("braindump")


def setup_logging(level: int = logging.INFO) -> None:
    """Configure braindump logging with consistent format."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(level)
    # Prevent duplicate messages if called multiple times
    logger.propagate = False
