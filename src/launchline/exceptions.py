"""Project-specific exception hierarchy.

All custom exceptions inherit from ``LaunchLineError`` so callers can
catch the entire family with a single ``except`` clause when needed.
"""

from __future__ import annotations


class LaunchLineError(Exception):
    """Base exception for all LaunchLine errors.

    Subclassed by every domain-specific exception so that callers may
    catch ``LaunchLineError`` as a generic fallback.
    """


class ConfigurationError(LaunchLineError):
    """Raised when a configuration file is invalid, missing, or malformed."""


class LaunchError(LaunchLineError):
    """Raised when a configured command fails to launch.

    Attributes:
        command: The command string that failed.
        reason: A human-readable explanation of the failure.
    """

    def __init__(self, command: str, reason: str) -> None:
        """Initialise with the failed command and a reason string.

        Args:
            command: The command that could not be executed.
            reason: Why the launch failed (e.g. file not found).
        """
        super().__init__(f"Failed to launch '{command}': {reason}")
        self.command = command
        self.reason = reason
