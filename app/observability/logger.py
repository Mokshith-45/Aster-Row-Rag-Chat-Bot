"""Safe structured request traces."""

import json
import logging
from typing import Any


logger = logging.getLogger("aster_row.agent")


def log_trace(trace: dict[str, Any]) -> None:
    """Emit a JSON trace containing only application-safe values."""
    logger.info(json.dumps(trace, sort_keys=True, default=str))