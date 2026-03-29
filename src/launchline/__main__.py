"""Application entry point for the LaunchLine launcher.

When executed as ``python -m launchline``, the :func:`main` function
parses CLI arguments, configures logging, and delegates to
:class:`Application` which runs the interactive launcher loop.
"""

from __future__ import annotations

import sys

from launchline.config import ConfigLoader, LaunchLineConfig
from launchline.exceptions import LaunchError, LaunchLineError


class Application:
    """Top-level application controller for the launcher loop.

    Owns the UI and runner instances and repeatedly presents the
    launcher menu until the user exits or ``on_exit`` is ``"exit"``.
    """

    def __init__(self, config: LaunchLineConfig) -> None:
        """Initialise the application with a validated configuration.

        Args:
            config: The loaded and validated launcher configuration.
        """
        self._config = config

    def run(self) -> None:
        """Run the interactive launcher loop.

        Presents the TUI, launches the selected entry, and either
        re-displays the menu (``on_exit="restart"``) or terminates
        (``on_exit="exit"``).
        """
        from launchline.ui import LaunchLineUI

        ui = LaunchLineUI(self._config)
        runner = None

        while True:
            selected = ui.run()
            if selected is None:
                break

            if runner is None:
                from launchline.runner import EntryRunner

                runner = EntryRunner(self._config)

            try:
                exit_code = runner.launch(selected)
            except LaunchError as exc:
                print(f"\nError: {exc}", file=sys.stderr)
                if self._config.on_exit == "exit":
                    sys.exit(1)
                input("Press Enter to return to the launcher...")
                continue
            except KeyboardInterrupt:
                if self._config.on_exit == "exit":
                    sys.exit(130)
                continue

            if self._config.on_exit == "exit":
                sys.exit(exit_code)
            # on_exit == "restart": loop continues


def main() -> None:
    """Parse arguments, configure logging, and run the launcher."""
    import logging

    from launchline.cli import CommandLineInterface

    args = CommandLineInterface.parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    try:
        config_existed = args.config is not None or ConfigLoader.DEFAULT_PATH.exists()
        config_path = ConfigLoader.resolve_path(args.config)
        if not config_existed:
            print(f"Created starter config at {config_path}")
            print("Edit it to add your tools, then run launchline again.\n")
        config = ConfigLoader.load(config_path)
    except LaunchLineError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    Application(config).run()


if __name__ == "__main__":
    main()
