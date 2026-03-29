"""Command-line interface definition."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse and validate command-line arguments.

    Args:
        argv: Argument list. Defaults to sys.argv[1:] when None.

    Returns:
        Parsed argument namespace with ``config`` and ``log_level`` attributes.
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
