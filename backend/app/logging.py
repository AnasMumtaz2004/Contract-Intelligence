import logging


def setup_logging() -> None:
    """Set one simple log format for the whole app."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )