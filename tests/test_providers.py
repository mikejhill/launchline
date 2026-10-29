"""Actual provider process success, bounded failure and cleanup contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from launchline.config import EntryConfig, ProviderConfig
from launchline.providers import MenuProvider, ProcessTree, ProviderError


class TestProcessTreeCleanup:
    """Keep transient Darwin teardown distinct from real permission failures."""

    def test_exited_darwin_group_can_disappear_after_eperm(self) -> None:
        """An all-zombie group must not replace a provider's real result/error."""
        process = MagicMock()
        process.poll.return_value = 0
        with (
            patch("launchline.providers.sys") as platform,
            patch("launchline.providers.signal.SIGKILL", 9, create=True),
            patch("launchline.providers.os.killpg", create=True) as kill_group,
            patch("launchline.providers.time.sleep"),
        ):
            platform.platform = "darwin"
            kill_group.side_effect = [
                PermissionError(1, "zombies"),
                ProcessLookupError(),
            ]
            ProcessTree(process).close()
        assert kill_group.call_count == 2

    @pytest.mark.parametrize(
        ("platform_name", "returncode"), [("darwin", None), ("linux", 0)]
    )
    def test_real_permission_failure_is_preserved(
        self, platform_name: str, returncode: int | None
    ) -> None:
        """A live child or a different OS must retain the permission failure."""
        process = MagicMock()
        process.poll.return_value = returncode
        with (
            patch("launchline.providers.sys") as platform,
            patch("launchline.providers.signal.SIGKILL", 9, create=True),
            patch("launchline.providers.os.killpg", create=True) as kill_group,
        ):
            platform.platform = platform_name
            kill_group.side_effect = PermissionError(1, "denied")
            with pytest.raises(PermissionError):
                ProcessTree(process).close()
        assert kill_group.call_count == 1

    def test_persistent_darwin_permission_failure_is_bounded(self) -> None:
        """An exited leader does not authorize ignoring inaccessible descendants."""
        process = MagicMock()
        process.poll.return_value = 0
        with (
            patch("launchline.providers.sys") as platform,
            patch("launchline.providers.signal.SIGKILL", 9, create=True),
            patch("launchline.providers.os.killpg", create=True) as kill_group,
            patch("launchline.providers.time.sleep"),
        ):
            platform.platform = "darwin"
            kill_group.side_effect = PermissionError(1, "persistent")
            with pytest.raises(PermissionError):
                ProcessTree(process).close()
        assert kill_group.call_count == 10


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

    @pytest.mark.skipif(sys.platform != "darwin", reason="Darwin process-group race")
    def test_repeated_oversized_providers_preserve_the_limit_error(self) -> None:
        """Exercise native fast-exit cleanup repeatedly on each macOS CI version."""
        code = "import sys; sys.stdout.write('x' * 1100000)"
        for _ in range(20):
            with pytest.raises(ProviderError, match="exceeds"):
                MenuProvider().resolve(self._config(code), depth=0)

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
