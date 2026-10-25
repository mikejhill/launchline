"""Bounded UI benchmarks with raw samples, profiles, and no timing gates."""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import os
import platform
import pstats
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import redirect_stdout
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from unittest.mock import patch

from launchline.config import EntryConfig, LaunchLineConfig
from launchline.ui import LaunchLineUI


class Sink:
    """Discard output without accumulating benchmark frames in memory."""

    def write(self, value: str) -> int:
        """Accept one buffered terminal write."""
        return len(value)

    def flush(self) -> None:
        """Accept terminal flushes."""


class Benchmark:
    """Measure warm operations separately from fresh-process startup."""

    @staticmethod
    def measure(operation: Callable[[], object], loops: int) -> dict[str, object]:
        """Warm up once and retain nine batch means in microseconds."""
        operation()
        samples = []
        for _ in range(9):
            start = time.perf_counter_ns()
            for _ in range(loops):
                operation()
            samples.append((time.perf_counter_ns() - start) / loops / 1000)
        ordered = sorted(samples)
        return {
            "samples_us": samples,
            "median_us": statistics.median(samples),
            "min_us": ordered[0],
            "max_us": ordered[-1],
            "loops": loops,
        }

    @classmethod
    def main(cls) -> None:
        """Record realistic fixture sizes and profile the largest menu."""
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("output", type=Path)
        args = parser.parse_args()
        result: dict[str, object] = {
            "started_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "terminal": [100, 30],
            "method": "9 warm batch means; startup fresh processes with warm OS caches",
            "ui_sha256": hashlib.sha256(
                Path("src/launchline/ui.py").read_bytes()
            ).hexdigest(),
        }
        measurements = {}
        with (
            redirect_stdout(Sink()),
            patch(
                "launchline.ui._get_terminal_size",
                return_value=os.terminal_size((100, 30)),
            ),
        ):
            for count in (10, 1000, 10000):
                config = LaunchLineConfig(
                    entries=tuple(
                        EntryConfig(
                            f"Project {index:05d} tool",
                            "unused",
                            description="Open project",
                        )
                        for index in range(count)
                    ),
                    numeric_trigger=False,
                )
                ui = LaunchLineUI(config)
                ui._reset()
                operations: dict[str, tuple[Callable[[], object], int]] = {
                    "construct": (partial(LaunchLineUI, config), 10),
                    "navigate": (partial(ui._on_key, "down"), 100),
                    "render": (ui._render, 30),
                }
                for name, (operation, loops) in operations.items():
                    measurements[f"{count}/{name}"] = cls.measure(operation, loops)
                for query in ("pt", "project", "999", "zz"):
                    ui._query = query
                    measurements[f"{count}/search/{query}"] = cls.measure(
                        ui._update_filter, 5
                    )
                ui._query = ""
                ui._update_filter()
            profile = cProfile.Profile()
            profile.enable()
            for _ in range(100):
                ui._on_key("down")
                ui._render()
            profile.disable()
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(18)
        result["profile"] = stream.getvalue()
        result["measurements"] = measurements
        for name, command in {
            "import": ["-c", "import launchline.ui"],
            "help": ["-m", "launchline", "--help"],
        }.items():
            samples = []
            for _ in range(9):
                start = time.perf_counter_ns()
                subprocess.run(
                    [sys.executable, *command], check=True, capture_output=True
                )
                samples.append((time.perf_counter_ns() - start) / 1e6)
            result[f"{name}_ms"] = samples
        result["finished_utc"] = datetime.now(UTC).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        sys.stdout.write(f"Benchmark evidence: {args.output}\n")


if __name__ == "__main__":
    Benchmark.main()
