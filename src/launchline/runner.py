"""Subprocess execution, screen clearing, and terminal title management.

This module provides :class:`EntryRunner`, which is responsible for
launching user-configured entries as subprocesses, managing the terminal
screen between launches, and setting the terminal title bar text.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from launchline.config import EntryConfig, LaunchLineConfig
from launchline.exceptions import LaunchError

logger = logging.getLogger(__name__)


class EntryRunner:
    """Launches a configured entry as a subprocess.

    Handles platform-specific command wrapping (e.g. ``cmd.exe /c`` for
    batch files on Windows), environment variable expansion, and
    optional screen clearing between launches.
    """

    def __init__(self, config: LaunchLineConfig) -> None:
        """Initialise the runner with the application configuration.

        Args:
            config: Top-level launcher configuration controlling
                behaviours such as ``clear_on_launch``.
        """
        self._config = config

    def launch(self, entry: EntryConfig) -> int:
        """Launch an entry's command as a subprocess.

        Args:
            entry: The entry to launch.

        Returns:
            The subprocess exit code.

        Raises:
            LaunchError: If the command cannot be found or executed.
        """
        title = (
            f"{entry.title_prefix} {entry.name}".strip()
            if entry.title_prefix
            else entry.name
        )
        self._set_terminal_title(title)

        if self._config.clear_on_launch:
            self._clear_screen()

        env = os.environ.copy()
        for key, value in entry.env.items():
            env[key] = str(Path(value).expanduser()) if "~" in value else value

        cwd: str | None = None
        if entry.working_directory is not None:
            cwd = str(entry.working_directory)

        cmd = [entry.command, *entry.args]
        if sys.platform == "win32" and Path(entry.command).suffix.lower() in (
            ".bat",
            ".cmd",
        ):
            cmd = ["cmd.exe", "/c", *cmd]
        logger.info("Launching: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                env=env,
                cwd=cwd,
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        except FileNotFoundError as exc:
            raise LaunchError(
                entry.command, f"Command not found: {entry.command}"
            ) from exc
        except OSError as exc:
            raise LaunchError(entry.command, str(exc)) from exc
        else:
            return result.returncode

    @staticmethod
    def _clear_screen() -> None:
        """Clear the terminal screen and reset cursor to top-left."""
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

    @staticmethod
    def _set_terminal_title(title: str) -> None:
        """Set the terminal tab/window title via OSC escape sequence."""
        sys.stdout.write(f"\033]0;{title}\a")
        sys.stdout.flush()
