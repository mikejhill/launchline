# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed

- Reverted array syntax for `command` config key; `command` is string-only,
  use `args` for arguments

### Changed

- Improved test naming to follow `[unit]_[scenario]_[expectedResult]` pattern
- Added diagnostic failure messages to all test assertions
- Release workflow now supports `force-patch` input for non-bumping commits

## [0.2.0] - 2026-03-30

### Added

- `--config-path` CLI flag to print the active configuration file path

### Fixed

- PyPI package page now renders README images correctly (paths are rewritten
  to absolute URLs during the release build)
- Release artifacts no longer accidentally include non-distribution files
- Release workflow now produces correct version numbers (fixed dirty-tree
  version detection via `SETUPTOOLS_SCM_PRETEND_VERSION`)

## [0.1.0] - 2026-03-30

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
