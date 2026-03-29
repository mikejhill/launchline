"""Subprocess execution, screen clearing, and post-exit logic."""

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
    """Launches a configured entry as a subprocess."""

    def __init__(self, config: LaunchLineConfig) -> None:
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
        self._set_terminal_title(entry.name)

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
