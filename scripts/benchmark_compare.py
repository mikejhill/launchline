"""Compare baseline and current search using identical warmed workloads."""

from __future__ import annotations

import json
import statistics
import subprocess
import time
from pathlib import Path

from launchline.fuzzy import FuzzyMatcher


class BenchmarkComparison:
    """Retain raw samples and avoid nondeterministic timing assertions."""

    @staticmethod
    def main() -> None:
        """Measure baseline Git source and installed current code in one process."""
        root = Path(__file__).resolve().parents[1]
        baseline = subprocess.check_output(
            ["git", "show", "904ace1:src/launchline/fuzzy.py"],
            cwd=root,
            text=True,
            encoding="utf-8",
        )
        namespace: dict[str, object] = {}
        exec(compile(baseline, "baseline_fuzzy.py", "exec"), namespace)
        old = namespace["FuzzyMatcher"]
        workloads = [
            ("exact", "powershell", "PowerShell"),
            ("prefix-long-tail", "abc", "abc" + "x" * 4096),
            ("sparse", "az", "a" + "x" * 128 + "z"),
            ("miss-long", "z", "x" * 4096),
            ("unicode", "猫é", "猫 café"),
        ]
        records = []
        for name, query, candidate in workloads:
            expected = FuzzyMatcher.score(query, candidate)
            for label, matcher in [("baseline", old), ("current", FuzzyMatcher)]:
                samples = []
                for _ in range(7):
                    start = time.perf_counter_ns()
                    for _ in range(1000):
                        result = matcher.score(query, candidate)
                    elapsed = (time.perf_counter_ns() - start) / 1000
                    assert result == expected, (name, label, result, expected)
                    samples.append(elapsed)
                records.append(
                    {
                        "workload": name,
                        "implementation": label,
                        "ns_per_call": samples,
                        "median_ns": statistics.median(samples),
                        "score": expected,
                    }
                )
        (root / "docs/validation/search-comparison.json").write_text(
            json.dumps(records, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    BenchmarkComparison.main()
