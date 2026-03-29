"""Command-line interface definition.

Provides :class:`CommandLineInterface` which encapsulates the
``argparse`` setup and validation for the ``launchline`` CLI.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path


class CommandLineInterface:
    """Command-line argument parser for LaunchLine.

    All methods are static; the class serves as a logical namespace.
    """

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

        args = parser.parse_args(argv)
        args.log_level = getattr(logging, args.log_level)
        return args
