"""Send the run log to stderr as bare JSON lines, at the configured level.

The scripts are the application, so they choose where logs go; ``core`` only
emits (Python logging cookbook: configuring handlers is "the responsibility of
the application developer, not the library developer"). Stderr, because a
process writes its log as a stream and lets the environment route it (The
Twelve-Factor App, "Logs"), and stdout already carries the extraction result.

Only the run logger is configured: a line holds nothing but the JSON (no level
or logger prefix), so ``jq`` or a log shipper reads it as is. Its records do
not propagate to the root, so another handler cannot print them twice. Other
libraries keep Python's default: warnings and errors still reach stderr.
"""

import logging.config

from doc_intake.core.config import LogLevel
from doc_intake.core.runlog import RUN_LOGGER


def configure_run_log(level: LogLevel) -> None:
    """Idempotent: a non-incremental ``dictConfig`` replaces the logger's handlers."""
    logging.config.dictConfig(
        {
            "version": 1,
            # The default (True) would disable every logger created so far,
            # the provider SDK's included, hiding their warnings.
            "disable_existing_loggers": False,
            "formatters": {"bare": {"format": "%(message)s"}},
            "handlers": {
                "stderr": {
                    "class": "logging.StreamHandler",
                    "formatter": "bare",
                    "stream": "ext://sys.stderr",
                }
            },
            "loggers": {RUN_LOGGER: {"level": level, "handlers": ["stderr"], "propagate": False}},
        }
    )
