# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

### Added

- Interactive TUI launcher with numbered shortcuts and fuzzy search
- TOML configuration with `[settings]` and `[[entries]]` tables
- Per-entry environment variables and working directory support
- Configurable on-exit behavior: restart loop or exit
- Auto-generated starter config on first run
- Configurable `show_exit` setting to show/hide Exit entry
- Windows Terminal integration support
- Kitty keyboard protocol support
- `ghost_text` feature flag for autocomplete hints on the prompt line
- `numeric_trigger` feature flag for immediate digit-key launching
- Bundled icon accessible via `launchline --icon-path` for Windows Terminal profiles
- Cross-platform support (Windows, macOS, Linux)
- LaunchLine icon (SVG, ICO, PNG) in `assets/`
- PyPI publishing via GitHub Actions with OIDC trusted publishers
