"""Actual provider process success, bounded failure and cleanup contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from launchline.config import EntryConfig, ProviderConfig
from launchline.providers import MenuProvider, ProviderError


class TestMenuProvider:
    """Run real children rather than mocking subprocess behavior."""

    @staticmethod
    def _config(
        code: str, *, timeout: int = 10, directory: Path | None = None
    ) -> ProviderConfig:
        """Build a harmless Python provider with explicit argv and deadline."""
        return ProviderConfig(
            EntryConfig(
                "provider", sys.executable, ("-c", code), working_directory=directory
            ),
            timeout,
        )

    def test_real_provider_receives_closed_stdin_and_returns_nested_entries(
        self, tmp_path: Path
    ) -> None:
        """Only successful UTF-8 JSON snapshots are converted to typed menu entries."""
        record = {
            "entries": [{"id": "projects", "name": "Projects", "menu": {"entries": []}}]
        }
        code = (
            "import sys,os; assert sys.stdin.read() == ''; assert os.getcwd() == "
            + repr(str(tmp_path))
            + "; sys.stdout.write("
            + repr(json.dumps(record))
            + ")"
        )
        result = MenuProvider().resolve(self._config(code, directory=tmp_path), depth=0)
        assert result[0].menu is not None, "Actual provider must create a typed submenu"
        assert result[0].id == "projects", "Actual provider must create a typed submenu"

    @pytest.mark.parametrize(
        ("code", "message"),
        [
            ("raise SystemExit(7)", "status 7"),
            ("import sys; sys.stdout.write('not json')", "Invalid provider result"),
            (
                "import sys; sys.stdout.buffer.write(b'\\xff')",
                "Invalid provider result",
            ),
            ("import sys; sys.stdout.write('{}')", "entries array"),
            (
                'import sys; sys.stdout.write(\'{"entries":[{"name":"broken"}]}\')',
                "required",
            ),
            (
                "import sys,json;sys.stdout.write("
                "json.dumps(dict(entries=[],padding='x'*1100000)))",
                "exceeds",
            ),
            (
                "import time,sys,json;time.sleep(3);"
                "sys.stdout.write(json.dumps(dict(entries=[])))",
                "timed out",
            ),
        ],
    )
    def test_real_process_failures_are_bounded_and_rejected(
        self, code: str, message: str
    ) -> None:
        """Reject failed, malformed, oversized or timed-out providers."""
        with pytest.raises(ProviderError, match=message):
            MenuProvider().resolve(self._config(code, timeout=1), depth=0)

    def test_empty_output_array_is_valid(self) -> None:
        """An empty generated menu is successful and can expose Back or Refresh."""
        result = MenuProvider().resolve(
            self._config("import sys; sys.stdout.write('{\"entries\":[]}')"), depth=0
        )
        assert result == (), (
            "Empty snapshots must remain distinguishable from provider errors"
        )

    def test_nonexistent_and_implicit_batch_provider_fail_cleanly(self) -> None:
        """Report missing executables and unsupported implicit batch files."""
        for command in ("nonexistent-provider-command-91c7", "provider.cmd"):
            with pytest.raises(ProviderError):
                MenuProvider().resolve(
                    ProviderConfig(EntryConfig("p", command)), depth=0
                )


class TestSharedProviderContract:
    """Use actual processes to emit every shared JSON boundary fixture."""

    def test_shared_json_results(self) -> None:
        """Unicode, numbers, nulls and nesting must agree with the native parser."""
        data = json.loads(
            (Path(__file__).parent / "fixtures/menu-contract.json").read_text(
                encoding="utf-8"
            )
        )
        for case in data["providers"]:
            code = (
                "import sys; sys.stdout.buffer.write(bytes.fromhex("
                + repr(case["json"].encode("utf-8").hex())
                + "))"
            )
            declaration = TestMenuProvider._config(code)
            if case["valid"]:
                assert MenuProvider().resolve(declaration, depth=0) is not None, case[
                    "name"
                ]
            else:
                with pytest.raises(ProviderError):
                    MenuProvider().resolve(declaration, depth=0)
