"""Structured JSON logs.

Log ids, counts, step names and error kinds. Never log an access code, CV
text, vacancy text or personal data (CLAUDE.md rules 12 and 15).
"""

import logging

import structlog


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
