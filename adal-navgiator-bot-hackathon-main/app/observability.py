import logging


def configure_logging(level: str) -> None:
    """Set readable server logs; application log messages must not include user content or secrets."""
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
