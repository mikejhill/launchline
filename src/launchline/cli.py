"""Command-line interface definition.

Provides :class:`CommandLineInterface` which encapsulates the
``argparse`` setup and validation for the ``launchline`` CLI.
"""

from __future__ import annotations

import argparse
import logging
from importlib.resources import files
from pathlib import Path


class CommandLineInterface:
    """Command-line argument parser for LaunchLine.

    All methods are static; the class serves as a logical namespace.
    """

    @staticmethod
    def icon_path() -> Path:
        """Return the path to the bundled LaunchLine icon.

        Returns:
            Absolute path to the ``.ico`` file shipped with the package.
        """
        resource = files("launchline").joinpath("assets", "launchline.ico")
        return Path(str(resource))

    @staticmethod
    def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
        """Parse and validate command-line arguments.

        Args:
            argv: Argument list to parse.  Defaults to ``sys.argv[1:]``
                when ``None``.

        Returns:
            Parsed argument namespace with ``config`` (``Path | None``)
            and ``log_level`` (``int``) attributes.
        """
        parser = argparse.ArgumentParser(
            prog="launchline",
            description="A lightweight launcher for interactive CLI tools.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument(
            "--config",
            type=Path,
            default=None,
            help="Path to config TOML (overrides env var and default path).",
        )
        parser.add_argument(
            "--log-level",
            type=str,
            default="WARNING",
            choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            help="Logging verbosity (default: %(default)s).",
        )
        parser.add_argument(
            "--icon-path",
            action="store_true",
            default=False,
            help="Print the path to the bundled icon and exit.",
        )
        parser.add_argument(
            "--config-path",
            action="store_true",
            default=False,
            help="Print the path to the active config file and exit.",
        )

        args = parser.parse_args(argv)
        args.log_level = getattr(logging, args.log_level)
        return args
