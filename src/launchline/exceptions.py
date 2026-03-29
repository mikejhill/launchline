"""Project-specific exception hierarchy."""

from __future__ import annotations


class LaunchLineError(Exception):
    """Base exception for LaunchLine."""


class ConfigurationError(LaunchLineError):
    """Raised when configuration is invalid or missing."""


class LaunchError(LaunchLineError):
    """Raised when a command fails to launch."""

    def __init__(self, command: str, reason: str) -> None:
        super().__init__(f"Failed to launch '{command}': {reason}")
        self.command = command
        self.reason = reason
