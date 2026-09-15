# Copyright 2026 AxonFlow
# SPDX-License-Identifier: MIT

"""Collects what the plugin logs, so a runtime test can assert on the notices a user sees."""

from __future__ import annotations

import logging

PLUGIN_LOGGER = "axonflow_adk.plugin"


class PluginLog(logging.Handler):
    """Every record the plugin logs at `level` or above, as formatted messages."""

    def __init__(self, level: int = logging.WARNING) -> None:
        super().__init__(level=level)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def capture_plugin_log(level: int = logging.WARNING) -> PluginLog:
    """Attach a collector to the plugin's logger and return it."""
    handler = PluginLog(level)
    logger = logging.getLogger(PLUGIN_LOGGER)
    logger.addHandler(handler)
    if logger.getEffectiveLevel() > level:
        logger.setLevel(level)
    return handler
