"""Application entry point."""

from __future__ import annotations

import sys


def main() -> None:
    """Parse arguments, configure logging, and run the launcher loop."""
    import logging

    from launchline.cli import parse_args
    from launchline.config import DEFAULT_CONFIG_PATH, load_config, resolve_config_path
    from launchline.exceptions import LaunchError, LaunchLineError

    args = parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    try:
        config_existed = args.config is not None or DEFAULT_CONFIG_PATH.exists()
        config_path = resolve_config_path(args.config)
        if not config_existed:
            print(f"Created starter config at {config_path}")
            print("Edit it to add your tools, then run launchline again.\n")
        config = load_config(config_path)
    except LaunchLineError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    from launchline.ui import LaunchLineUI

    ui = LaunchLineUI(config)
    runner = None

    while True:
        selected = ui.run()
        if selected is None:
            break

        if runner is None:
            from launchline.runner import EntryRunner

            runner = EntryRunner(config)

        try:
            exit_code = runner.launch(selected)
        except LaunchError as exc:
            print(f"\nError: {exc}", file=sys.stderr)
            if config.on_exit == "exit":
                sys.exit(1)
            input("Press Enter to return to the launcher...")
            continue
        except KeyboardInterrupt:
            if config.on_exit == "exit":
                sys.exit(130)
            continue

        if config.on_exit == "exit":
            sys.exit(exit_code)
        # on_exit == "restart": loop continues


if __name__ == "__main__":
    main()
