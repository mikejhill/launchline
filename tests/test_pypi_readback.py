"""Exercise the actual inline registry verifier against delayed/conflicting reads."""

from __future__ import annotations

import hashlib
import io
import json
import textwrap
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


class TestPyPIReadback:
    """Retry only absent/incomplete registry views; conflicts always fail closed."""

    @pytest.mark.parametrize(
        ("scenario", "calls", "sleeps", "error"),
        [
            ("visible", 1, 0, None),
            ("delayed", 3, 2, None),
            ("absent", 12, 11, ValueError),
            ("partial", 12, 11, ValueError),
            ("version", 1, 0, ValueError),
            ("digest", 1, 0, ValueError),
            ("unexpected", 1, 0, ValueError),
            ("http-error", 1, 0, urllib.error.HTTPError),
            ("malformed", 1, 0, json.JSONDecodeError),
        ],
    )
    def test_bounded_readback(
        self,
        scenario: str,
        calls: int,
        sleeps: int,
        error: type[Exception] | None,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Run unchanged workflow Python with only network, time and cwd replaced."""
        root = Path(__file__).resolve().parents[1]
        workflow = yaml.safe_load(
            (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
        )
        step = next(
            step
            for step in workflow["jobs"]["pypi"]["steps"]
            if step.get("name") == "Verify complete published PyPI distributions"
        )
        source = textwrap.dedent(step["run"]).split("\n", 1)[1].rsplit("\nPY", 1)[0]
        distribution = tmp_path / "release/dist"
        distribution.mkdir(parents=True)
        (distribution / "fixture.whl").write_bytes(b"tested wheel")
        (distribution / "fixture.tar.gz").write_bytes(b"tested sdist")
        artifacts = [
            {"filename": name, "digests": {"sha256": hashlib.sha256(data).hexdigest()}}
            for name, data in (
                ("fixture.whl", b"tested wheel"),
                ("fixture.tar.gz", b"tested sdist"),
            )
        ]
        count = 0

        def read(url: str, *, timeout: int) -> io.StringIO:
            nonlocal count
            count += 1
            assert url == "https://pypi.org/pypi/launchline/0.4.3/json"
            assert timeout == 30
            if scenario == "absent" or (scenario == "delayed" and count == 1):
                raise urllib.error.HTTPError(url, 404, "Not visible", None, None)
            if scenario == "http-error":
                raise urllib.error.HTTPError(url, 503, "Unavailable", None, None)
            if scenario == "malformed":
                return io.StringIO("invalid JSON")
            published = {"info": {"version": "0.4.3"}, "urls": artifacts}
            if scenario == "partial" or (scenario == "delayed" and count == 2):
                published["urls"] = artifacts[:1]
            if scenario == "version":
                published["info"]["version"] = "0.4.2"
            if scenario == "digest":
                artifacts[0]["digests"]["sha256"] = "0" * 64
            if scenario == "unexpected":
                artifacts[0]["filename"] = "foreign.whl"
            return io.StringIO(json.dumps(published))

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("VERSION", "0.4.3")
        with (
            patch("urllib.request.urlopen", side_effect=read),
            patch("time.sleep") as sleep,
        ):
            if error is None:
                exec(compile(source, "release.yml:PyPI-readback", "exec"), {})
            else:
                with pytest.raises(error):
                    exec(compile(source, "release.yml:PyPI-readback", "exec"), {})
        assert count == calls
        assert sleep.call_count == sleeps
        assert all(call.args == (10,) for call in sleep.call_args_list)
