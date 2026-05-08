from __future__ import annotations


class TailStrategyError(Exception):
    """Base exception for the tail strategy project."""


class ConfigError(TailStrategyError):
    """Raised when project configuration is missing or invalid."""


class QmtUnavailableError(TailStrategyError):
    """Raised when the QMT runtime is required but unavailable."""


class StorageError(TailStrategyError):
    """Raised when local storage cannot complete an operation."""
