# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.3](https://github.com/mikejhill/launchline/compare/v0.4.2...v0.4.3) (2026-10-29)


### Fixed

* validate uv build sidecars before release ([#9](https://github.com/mikejhill/launchline/issues/9)) ([7bf6845](https://github.com/mikejhill/launchline/commit/7bf68458d607a7b8f8d558674cdd2c5f5cfcc125))

## [0.4.2](https://github.com/mikejhill/launchline/compare/v0.4.1...v0.4.2) (2026-10-29)

Unpublished release attempt: the build stopped before registry upload because
uv's generated `.gitignore` was rejected. The provider fix below is included in
the subsequent patch release. The original source tag is preserved.

### Fixed

* retry transient Darwin provider group cleanup ([#7](https://github.com/mikejhill/launchline/issues/7)) ([0b6f4db](https://github.com/mikejhill/launchline/commit/0b6f4db4c4b1166aecbe504bb1796b901049032a))

## [Unreleased]

## [0.4.1] - 2026-10-25

### Changed

- Cache filtered menu rows and immutable alignment widths to avoid full-menu
  traversal on warm rendering and navigation.
- Add deterministic scaling checks, large-menu terminal coverage, bounded
  mutations, and separate fast and full release validation commands.
- Document timing distributions, construction tradeoffs, and concurrent-load
  limitations in [performance validation](docs/performance.md).

## [0.4.0] - 2026-10-23

### Added

- Add nested menus with Back navigation, lazy JSON providers, explicit refresh/retry,
  configurable parent refresh, and stable selection restoration.
- Bound generated output, provider timeouts and process cleanup; cache up to 128 menu
  snapshots with inactive least-recently-used eviction. Existing static configs remain valid.
- Add shared declaration fixtures, actual provider/terminal tests and seeded menu mutations.
  See [menu lifecycle and provider contract](docs/menus.md) for examples and limits.

## [0.3.0] - 2026-10-23

### Changed

- Align configuration, search scoring, keyboard handling, and child exit behavior
  with the Rust implementation; add cross-platform compatibility fixtures.
- Add strict typing, branch coverage, real-terminal and installed-package tests,
  bounded mutation checks, and measured search/startup validation.
- Isolate trusted release publication from read-only tests and builds, pin release
  tools and actions, protect source tags, and attest tested distributions.

## [0.2.1] - 2026-03-30

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
