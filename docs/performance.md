# Performance validation

Run `uv sync --locked --group dev` once, then choose a gate:

| Command | Purpose |
| --- | --- |
| `uv run poe check-fast` | Format, lint, strict types and deterministic tests; about 3 seconds of tests on the measured laptop |
| `uv run poe check` | Full branch coverage and real subprocess/terminal UX tests, including nested menus and a 1,000-entry search |
| `uv run poe release-check` | Full checks, distribution build, installed-wheel smoke, and bounded search/config/menu mutations |
| `uv run poe benchmark-ui` | Short informational benchmark; raw samples/profile in `.tmp/ui-current.json` |

Fast checks omit real-terminal and provider-process suites, and omit coverage
instrumentation. Full checks retain the existing 90% branch-aware coverage floor.
CI and release workflows continue to run the full checks and packaging/mutation
gates. Run mutations sequentially: they temporarily modify source and restore it
in `finally`; never overlap them with tests or benchmarks.

## Measured change

Baseline: Python `c7276e2` (v0.4.0). Candidate caches each filtered display snapshot
and computes immutable name/number widths once per UI instance. Filtering and
reset invalidate the snapshot; navigation and warm frames reuse it. Search
scoring, ordering, numeric shortcuts, menu lifecycle and rendering bytes retain
their existing behavior. Numbered wrappers use slots to reduce per-entry memory.

Windows 11 build 26300, CPython 3.12.13, 32 logical CPUs, fixed 100 by 30
terminal, ten visible rows. Fixtures contain 10, 1,000 and 10,000 named entries
with descriptions. Each operation warms once, then records nine batch means;
raw samples, batch sizes, source hashes and profiles are in
`docs/validation/ui-*-repeat.json`. The harness discards buffered stdout and fixes
terminal dimensions, so it measures UI composition rather than terminal paint
latency. Dimension mock overhead is included equally in both runs.

| Entries / operation | Baseline median µs | Candidate median µs | Baseline range | Candidate range |
| --- | ---: | ---: | ---: | ---: |
| 10 / render | 23.88 | 22.25 | 22.85–25.54 | 21.66–23.60 |
| 1,000 / render | 55.55 | 22.11 | 53.79–60.04 | 21.15–22.96 |
| 10,000 / render | 335.72 | 23.55 | 327.48–350.01 | 20.87–25.15 |
| 10,000 / navigate | 19.35 | 3.13 | 18.67–19.61 | 2.98–3.60 |
| 10,000 / construct | 2,281.63 | 2,517.70 | 2,226.83–2,748.10 | 2,398.32–2,830.43 |

Large-menu warm rendering is 14.3 times faster and navigation 6.2 times faster.
Construction pays one width scan (about 236 µs extra at 10,000 entries), recovered
within one subsequent frame in this fixture. A cached display list retains one
reference per visible match until invalidation. Search remains linear in menu
size; the four query classes (`pt`, `project`, `999`, `zz`) show no material
change. Profiling 100 navigation/frame pairs drops from approximately 2,020,601
calls to 20,002 calls, removing repeated name scans and menu copies.

Fresh-process import/help medians were 194.59/205.58 ms before and 185.82/196.02 ms
after. No startup improvement is claimed: those paths were unchanged and the
difference is host noise. These are fresh interpreters with warm filesystem
caches, not a cold disk or reboot benchmark. Warm operation timing excludes
construction, initial imports and config parsing. The real CLI suite separately
checks startup, config errors, keyboard input, cancellation and child execution.

The repeat window was 2026-10-25 17:10:59–17:11:13 UTC. Host CPU samples were 23%
before and after. Other local validation was stopped during measurement;
background applications/monitoring remained active. Initial paired runs showed
the same large-menu effect. Laptop distributions are evidence, not portable
latency guarantees. No prolonged stress load or power/thermal changes were used.

## Regression strategy

`tests/test_ui_performance.py` rejects full-menu traversal during warm frames
for all fixture sizes and checks snapshot invalidation, exit visibility, restored
selection and alignment against offscreen names. These operation-count checks
fail independently of machine speed. Existing shared score/menu fixtures and
real-terminal flows protect Python/Rust compatibility; the large-menu PTY test
checks that filtering launches exactly the chosen leaf. Three additional seeded
mutations verify that repeated copies, stale filter snapshots and lost alignment
are detected. Timing has no brittle pass/fail threshold.

For new measurements, stop your own tests/builds first, sample host activity,
keep monitoring overhead consistent, record timestamps and rerun baseline and
candidate sequentially with the same Python, harness and fixture sizes. Review
raw distributions and construction/startup tradeoffs before claiming a gain.
