"""Shared validation, real-process, search, and interrupted UX contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from launchline.config import ConfigLoader, EntryConfig, LaunchLineConfig
from launchline.exceptions import ConfigurationError
from launchline.fuzzy import FuzzyMatcher
from launchline.runner import EntryRunner
from launchline.ui import LaunchLineUI


class TestContract:
    """Exercise observable behavior across trust and runtime boundaries."""

    @pytest.mark.parametrize(
        "source",
        [
            "settings = 1",
            '[settings]\nshow_exit = "yes"',
            "[settings]\ntitle = 123",
            '[[entries]]\nname = "x"\ncommand = 12',
            '[[entries]]\nname = "x"\ncommand = "x"\nargs = [1]',
            '[[entries]]\nname = "x"\ncommand = "x"\nenv = {A = false}',
            '[[entries]]\nname = "x\\u001b]0;bad"\ncommand = "x"',
            '[[entries]]\nname = "x"\ncommand = "x"\nenv = {"A=B" = "x"}',
        ],
    )
    def test_invalid_config_is_rejected(self, tmp_path: Path, source: str) -> None:
        """Reject malformed types and terminal-control injection."""
        path = tmp_path / "config.toml"
        if "[[entries]]" not in source:
            source += '\n[[entries]]\nname="safe"\ncommand="unused"\n'
        path.write_text(source, encoding="utf-8")
        with pytest.raises(ConfigurationError):
            ConfigLoader.load(path)

    @pytest.mark.parametrize(
        ("query", "candidate", "score"),
        [
            ("", "", 0),
            ("abc", "abc", 10),
            ("ab", "a-b", 8),
            ("ab", "ba", None),
            ("é", "Éclair", 4),
            ("猫", "猫工具", 4),
            ("i\u0307", "İ", 7),
            ("abc", "abc" + "x" * 4096, 10),
        ],
    )
    def test_exact_search_scores(
        self, query: str, candidate: str, score: int | None
    ) -> None:
        """Keep exact scoring semantics after the performance change."""
        assert FuzzyMatcher.score(query, candidate) == score, (query, candidate, score)

    def test_real_child_receives_argv_env_cwd_and_exit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Launch a real child without shell interpretation or parent env mutation."""
        output = tmp_path / "result.json"
        child = tmp_path / "child.py"
        child.write_text(
            "import json, os, pathlib, sys; "
            "pathlib.Path(sys.argv[1]).write_text(json.dumps([sys.argv[2:], "
            "os.environ['LL_CONTRACT'], os.getcwd()])); sys.exit(7)",
            encoding="utf-8",
        )
        entry = EntryConfig(
            name="child",
            command=sys.executable,
            args=(str(child), str(output), "a b", "&literal", "猫"),
            env={"LL_CONTRACT": "isolated"},
            working_directory=tmp_path,
        )
        config = LaunchLineConfig(entries=(entry,), clear_on_launch=False)

        with child.open("r", encoding="utf-8") as child_input:
            monkeypatch.setattr(sys, "stdin", child_input)
            assert EntryRunner(config).launch(entry) == 7, (
                "Child exit code must propagate"
            )
        assert json.loads(output.read_text()) == [
            ["a b", "&literal", "猫"],
            "isolated",
            str(tmp_path),
        ], "Child must receive literal argv, overlay, and cwd"
        assert "LL_CONTRACT" not in os.environ, (
            "Overlay must not mutate parent environment"
        )

    @pytest.mark.parametrize(
        "args",
        [["--config-path", "--config", "missing.toml"], ["--config", "missing.toml"]],
    )
    def test_cli_config_failure_has_no_traceback(
        self, args: list[str], tmp_path: Path
    ) -> None:
        """Both CLI config paths report expected failures cleanly."""
        result = subprocess.run(
            [sys.executable, "-m", "launchline", *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, result.stderr
        assert "Traceback" not in result.stderr, result.stderr

    def test_unicode_digit_is_search_text(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A superscript digit must not crash numeric selection."""
        entry = EntryConfig(name="² tool", command="unused")
        keys = iter(["²", "enter"])
        ui = LaunchLineUI(
            LaunchLineConfig(entries=(entry,)), _key_reader=lambda: next(keys)
        )
        assert ui.run() == entry, "Unicode digit should fuzzy-match by name"
        assert "\x1b[?1049l" in capsys.readouterr().out, "Selection must restore screen"

    def test_read_failure_restores_terminal(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unexpected keyboard failure must still restore the main screen."""

        def fail() -> str:
            raise OSError("keyboard disconnected")

        ui = LaunchLineUI(
            LaunchLineConfig(entries=(EntryConfig("x", "x"),)), _key_reader=fail
        )
        with pytest.raises(OSError, match="disconnected"):
            ui.run()
        assert capsys.readouterr().out.endswith("\x1b[<u\x1b[?1049l"), (
            "Failure must pop protocol and screen"
        )


class TestWorkingDirectory:
    """Reject a regular file as a child working directory."""

    def test_file_path_falls_back_to_inherited_directory(self, tmp_path: Path) -> None:
        """An existing file must not be passed as subprocess cwd."""
        regular_file = tmp_path / "regular-file"
        regular_file.write_text("fixture", encoding="utf-8")
        config = tmp_path / "config.toml"
        config.write_text(
            '[[entries]]\nname="safe"\ncommand="unused"\nworking_directory='
            + json.dumps(str(regular_file)),
            encoding="utf-8",
        )
        assert ConfigLoader.load(config).entries[0].working_directory is None, (
            "Regular files are not valid working directories"
        )


class TestScoringCompatibility:
    """Compare optimized scoring to 405 captured baseline results."""

    def test_baseline_score_corpus_is_preserved(self) -> None:
        """Keep exact ASCII, Unicode, boundary, and sparse-match scores."""
        corpus = Path(__file__).parent / "fixtures/fuzzy.tsv"
        for line in corpus.read_text(encoding="utf-8").splitlines():
            query, candidate, expected_text = line.split("\t")
            expected = None if expected_text == "-1" else int(expected_text)
            assert FuzzyMatcher.score(query, candidate) == expected, (
                query,
                candidate,
                expected,
            )


class TestSignalStatus:
    """Normalize subprocess signal conventions consistently across runtimes."""

    @pytest.mark.parametrize(("status", "expected"), [(-2, 130), (-9, 137), (-15, 143)])
    def test_negative_signal_code_uses_shell_convention(
        self, status: int, expected: int
    ) -> None:
        """Convert negative subprocess signal codes to 128 plus signal."""
        entry = EntryConfig("safe", "unused")
        config = LaunchLineConfig(entries=(entry,), clear_on_launch=False)
        with (
            patch("launchline.runner.sys.platform", "linux"),
            patch(
                "subprocess.run", return_value=subprocess.CompletedProcess([], status)
            ),
        ):
            assert EntryRunner(config).launch(entry) == expected, (
                "Signal status must match the Rust shell-style convention"
            )

    @pytest.mark.skipif(
        sys.platform == "win32", reason="POSIX child signal exit status"
    )
    def test_real_child_sigterm_returns_143(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A child terminating only itself with SIGTERM must return 143."""
        child = tmp_path / "signal_child.py"
        child.write_text(
            "import os, signal; os.kill(os.getpid(), signal.SIGTERM)", encoding="utf-8"
        )
        entry = EntryConfig("signal fixture", sys.executable, args=(str(child),))
        config = LaunchLineConfig(entries=(entry,), clear_on_launch=False)
        with child.open("r", encoding="utf-8") as child_input:
            monkeypatch.setattr(sys, "stdin", child_input)
            assert EntryRunner(config).launch(entry) == 143, (
                "Actual SIGTERM must use the shared status"
            )


class TestWindowsStatus:
    """Distinguish Windows status values from POSIX negative signal codes."""

    @pytest.mark.parametrize(
        ("status", "expected"), [(-1073741510, 130), (3221225786, 130), (-1, -1)]
    )
    def test_windows_status_is_not_treated_as_posix_signal(
        self, status: int, expected: int
    ) -> None:
        """Map Ctrl+C specifically and preserve other Windows return values."""
        entry = EntryConfig("safe", "unused.exe")
        config = LaunchLineConfig(entries=(entry,), clear_on_launch=False)
        with (
            patch("launchline.runner.sys.platform", "win32"),
            patch(
                "subprocess.run", return_value=subprocess.CompletedProcess([], status)
            ),
        ):
            assert EntryRunner(config).launch(entry) == expected
