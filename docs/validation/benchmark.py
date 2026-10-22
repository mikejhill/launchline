"""Reproduce search microbenchmarks and CLI process startup samples."""

from __future__ import annotations
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from launchline.fuzzy import FuzzyMatcher


class Benchmark:
    """Record medians without pass/fail timing thresholds."""

    @staticmethod
    def main() -> None:
        """Write raw samples for a short match followed by a long tail."""
        samples = []
        for _ in range(7):
            start = time.perf_counter_ns()
            for _ in range(2000):
                assert FuzzyMatcher.score("abc", "abc" + "x" * 4096) == 10
            samples.append((time.perf_counter_ns() - start) / 2000)
        startup = []
        for _ in range(15):
            start = time.perf_counter_ns()
            subprocess.run(
                [sys.executable, "-m", "launchline", "--help"],
                check=True,
                capture_output=True,
            )
            startup.append((time.perf_counter_ns() - start) / 1e6)
        result = {
            "search_ns": samples,
            "search_median_ns": statistics.median(samples),
            "help_ms": startup,
            "help_median_ms": statistics.median(startup),
            "python": sys.version,
        }
        Path(sys.argv[1]).write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    Benchmark.main()
