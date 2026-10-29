"""Offline version, changelog, source and exact artifact preparation contracts."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
import yaml


class TestReleaseArtifacts:
    """Execute the actual release helper against disposable distribution fixtures."""

    @staticmethod
    def _fixture(
        root: Path, metadata_version: str = "0.4.1", build_version: str = "0.4.1"
    ) -> None:
        """Create minimal archives without installing or executing package code."""
        (root / "dist").mkdir()
        (root / ".release-please-manifest.json").write_text('{".":"0.4.1"}')
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [Unreleased]\n\n## [0.4.1] - 2026-10-25\n\n"
            "### Fixed\n\n- Reviewed change\n\n## [0.4.0] - 2026-10-23\n\n- Old\n"
        )
        metadata = f"Name: launchline\nVersion: {metadata_version}\n".encode()
        with zipfile.ZipFile(
            root / f"dist/launchline-{build_version}-py3-none-any.whl", "w"
        ) as wheel:
            wheel.writestr(f"launchline-{build_version}.dist-info/METADATA", metadata)
        with tarfile.open(
            root / f"dist/launchline-{build_version}.tar.gz", "w:gz"
        ) as sdist:
            member = tarfile.TarInfo(f"launchline-{build_version}/PKG-INFO")
            member.size = len(metadata)
            sdist.addfile(member, io.BytesIO(metadata))

    @staticmethod
    def _run(
        root: Path,
        version: str = "0.4.1",
        revision: str = "a" * 40,
        *,
        check_build: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run the same CLI as the build job with no remote service access."""
        script = Path(__file__).resolve().parents[1] / "scripts/release_artifacts.py"
        return subprocess.run(
            [sys.executable, str(script)]
            + (["--check-build"] if check_build else [version, revision]),
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

    @pytest.mark.parametrize("marker", [None, b"*", b"*\n", b"*\r\n"])
    def test_matching_archives_emit_source_hashes_and_reviewed_notes(
        self, tmp_path: Path, marker: bytes | None
    ) -> None:
        """Only reviewed versioned artifacts become the release evidence."""
        self._fixture(tmp_path)
        if marker is not None:
            (tmp_path / "dist/.gitignore").write_bytes(marker)
        result = self._run(tmp_path)
        assert result.returncode == 0, result.stderr
        manifest = json.loads((tmp_path / "release-manifest.json").read_text())
        assert manifest["version"] == "0.4.1"
        assert manifest["source_sha"] == "a" * 40
        assert len(manifest["sha256"]) == 2
        assert ".gitignore" not in manifest["sha256"]
        for name, digest in manifest["sha256"].items():
            assert (
                digest
                == hashlib.sha256((tmp_path / "dist" / name).read_bytes()).hexdigest()
            )
            assert f"{digest}  {name}\n" in (tmp_path / "SHA256SUMS").read_text()
        notes = (tmp_path / "release-notes.md").read_text()
        assert "Reviewed change" in notes
        assert "- Old" not in notes

    @pytest.mark.parametrize(
        "fault",
        [
            "version",
            "revision",
            "manifest",
            "changelog",
            "metadata",
            "extra-file",
            "hidden-file",
            "invalid-marker",
            "directory-marker",
        ],
    )
    def test_inconsistent_release_is_rejected_before_evidence(
        self, tmp_path: Path, fault: str
    ) -> None:
        """Fail closed for version/source/package/changelog inconsistencies."""
        self._fixture(tmp_path, "0.4.0" if fault == "metadata" else "0.4.1")
        if fault == "manifest":
            (tmp_path / ".release-please-manifest.json").write_text('{".":"0.4.0"}')
        elif fault == "changelog":
            (tmp_path / "CHANGELOG.md").write_text("# Changelog\n")
        elif fault == "extra-file":
            (tmp_path / "dist/unrelated.txt").write_text("unrelated")
        elif fault == "hidden-file":
            (tmp_path / "dist/.unexpected").write_text("unexpected")
        elif fault == "invalid-marker":
            (tmp_path / "dist/.gitignore").write_text("unexpected")
        elif fault == "directory-marker":
            (tmp_path / "dist/.gitignore").mkdir()
        result = self._run(
            tmp_path,
            "0.4.1-rc1" if fault == "version" else "0.4.1",
            "main" if fault == "revision" else "a" * 40,
        )
        assert result.returncode != 0
        assert not (tmp_path / "release-manifest.json").exists()

    def test_development_build_preflight_does_not_authorize_a_release(
        self, tmp_path: Path
    ) -> None:
        """Real CI builds can validate layout before a stable version is reviewed."""
        version = "0.4.3.dev1"
        self._fixture(tmp_path, version, version)
        (tmp_path / "dist/.gitignore").write_bytes(b"*")
        result = self._run(tmp_path, check_build=True)
        assert result.returncode == 0, result.stderr
        assert not (tmp_path / "release-manifest.json").exists()
        assert self._run(tmp_path, version).returncode != 0

    def test_marker_symlink_is_rejected(self, tmp_path: Path) -> None:
        """An accepted filename cannot hide a different source through a symlink."""
        self._fixture(tmp_path)
        target = tmp_path / "marker-target"
        target.write_bytes(b"*")
        try:
            (tmp_path / "dist/.gitignore").symlink_to(target)
        except OSError:
            pytest.skip("Host does not allow disposable symlink fixtures")
        assert self._run(tmp_path).returncode != 0


class TestRegistryRetry:
    """Exercise the real inline PyPI preflight with mocked HTTP only."""

    @pytest.mark.parametrize("require_complete", [False, True])
    @pytest.mark.parametrize(
        "scenario",
        [
            "new",
            "same",
            "partial",
            "conflict",
            "unknown-file",
            "wrong-version",
            "server-error",
        ],
    )
    def test_pypi_retry_requires_existing_bytes_to_match(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        scenario: str,
        require_complete: bool,
    ) -> None:
        """Allow absent/identical bytes and reject conflicts and HTTP errors."""
        import urllib.error
        from unittest.mock import patch

        root = Path(__file__).resolve().parents[1]
        workflow = yaml.safe_load((root / ".github/workflows/release.yml").read_text())
        step = workflow["jobs"]["pypi"]["steps"][1]["run"]
        code = step.split("\n", 1)[1].rsplit("\nPY", 1)[0]
        directory = tmp_path / "release/dist"
        directory.mkdir(parents=True)
        (directory / "fixture.whl").write_bytes(b"fixture")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("VERSION", "0.4.1")
        monkeypatch.setenv("REQUIRE_COMPLETE", "true" if require_complete else "false")
        digest = hashlib.sha256(b"fixture").hexdigest()
        payload = {
            "info": {"version": "0.4.0" if scenario == "wrong-version" else "0.4.1"},
            "urls": []
            if scenario == "partial"
            else [
                {
                    "filename": "unknown.whl"
                    if scenario == "unknown-file"
                    else "fixture.whl",
                    "digests": {
                        "sha256": "different" if scenario == "conflict" else digest
                    },
                }
            ],
        }
        response = io.BytesIO(json.dumps(payload).encode())
        error = urllib.error.HTTPError(
            "https://pypi.org/fixture",
            404 if scenario == "new" else 503,
            "fixture",
            {},
            None,
        )
        with patch(
            "urllib.request.urlopen",
            side_effect=error if scenario in {"new", "server-error"} else None,
            return_value=response,
        ):
            if scenario == "same" or (
                scenario in {"new", "partial"} and not require_complete
            ):
                exec(compile(code, "pypi-workflow", "exec"), {"__name__": "__main__"})
            else:
                with pytest.raises((ValueError, urllib.error.HTTPError)):
                    exec(
                        compile(code, "pypi-workflow", "exec"), {"__name__": "__main__"}
                    )


class TestReleaseArchitecture:
    """Keep release PR, source validation and publishing boundaries in the real YAML."""

    def test_release_pr_and_dispatch_keep_protections_and_current_version(self) -> None:
        """Bootstrap shipped 0.4.1 and dispatch complete CI without auto-approval."""
        root = Path(__file__).resolve().parents[1]
        content = (root / ".github/workflows/release.yml").read_text()
        workflow = yaml.safe_load(content)
        job = workflow["jobs"]["release-please"]
        action = job["steps"][0]
        assert (
            action["uses"] == "googleapis/release-please-action@"
            "45996ed1f6d02564a971a2fa1b5860e934307cf7"
        )
        assert action["with"]["token"] == "${{ github.token }}"
        assert workflow["permissions"] == {"contents": "read"}
        assert "force-patch" not in content
        assert "gh pr merge" not in content
        assert "gh pr review" not in content
        assert "/approve" not in content
        assert "--field expected-sha=" in content
        assert 'test "$actual" = "$GITHUB_SHA"' in job["steps"][1]["run"]
        manifest = json.loads((root / ".release-please-manifest.json").read_text())
        assert set(manifest) == {"."}
        assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest["."])
        assert "## [0.4.1]" in (root / "CHANGELOG.md").read_text()
        config = json.loads((root / "release-please-config.json").read_text())
        assert config["bootstrap-sha"] == "c76182b462e87143b21d4bb1cb16d0a1eddcffdc"
        assert config["release-type"] == "python"
        for name in ("build", "ci"):
            assert workflow["jobs"][name].get("permissions", {}) == {}
        for name in ("github-release", "pypi", "attest"):
            assert not any(
                "checkout@" in step.get("uses", "")
                for step in workflow["jobs"][name]["steps"]
            )
        assert workflow["jobs"]["attest"]["needs"] == "build"
        registry_steps = workflow["jobs"]["pypi"]["steps"]
        assert registry_steps[-1]["run"] == registry_steps[1]["run"]
        assert registry_steps[-1]["env"]["REQUIRE_COMPLETE"] == "true"
        assert (
            "scripts/release_artifacts.py"
            in workflow["jobs"]["build"]["steps"][2]["run"]
        )
        ci = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
        assert "expected-sha" in ci["on"]["workflow_dispatch"]["inputs"]
        assert "git rev-parse HEAD" in ci["jobs"]["check"]["steps"][1]["run"]


class TestReleaseDispatch:
    """Run actual dispatch guards with real jq and intercepted GitHub requests."""

    @pytest.mark.parametrize(
        "scenario", ["valid", "fork", "base", "closed", "branch", "unexpected-prefix"]
    )
    def test_only_expected_open_release_pr_dispatches_ci(
        self, tmp_path: Path, scenario: str
    ) -> None:
        """Reject wrong repository, target or branch before dispatching CI."""
        root = Path(__file__).resolve().parents[1]
        workflow = yaml.safe_load((root / ".github/workflows/release.yml").read_text())
        body = workflow["jobs"]["release-please"]["steps"][2]["run"]
        branch = "release-please--branches--main--components--launchline"
        if scenario == "unexpected-prefix":
            branch = "feature/unrelated"
        pr = {
            "headRefName": "different" if scenario == "branch" else branch,
            "headRefOid": "b" * 40,
            "headRepositoryOwner": {
                "login": "foreign" if scenario == "fork" else "fixture"
            },
            "baseRefName": "other" if scenario == "base" else "main",
            "state": "CLOSED" if scenario == "closed" else "OPEN",
        }
        fake = r"""
set -euo pipefail
gh() {
  case "$*" in
    "pr view"*) printf '%s' "$FIXTURE_PR" ;;
    "workflow run"*) printf '%s\n' "$*" > "$FIXTURE_LOG" ;;
    *) return 99 ;;
  esac
}
"""
        bash = (
            str(Path(os.environ["PROGRAMFILES"]) / "Git/bin/bash.exe")
            if sys.platform == "win32"
            else shutil.which("bash")
        )
        assert bash is not None
        log = tmp_path / "dispatch"
        result = subprocess.run(
            [bash, "-c", fake + body],
            cwd=tmp_path,
            env={
                **os.environ,
                "GITHUB_REPOSITORY": "fixture/launchline",
                "PR_JSON": json.dumps({"headBranchName": branch, "number": 17}),
                "FIXTURE_PR": json.dumps(pr),
                "FIXTURE_LOG": str(log).replace("\\", "/"),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert (result.returncode == 0) == (scenario == "valid"), result.stderr
        assert log.exists() == (scenario == "valid")
        if scenario == "valid":
            assert "expected-sha=" + "b" * 40 in log.read_text()

    @pytest.mark.parametrize("actual", ["b" * 40, "c" * 40])
    def test_dispatched_ci_refuses_a_moved_branch(
        self, tmp_path: Path, actual: str
    ) -> None:
        """Fail if a release PR branch moves before the matrix checkout."""
        root = Path(__file__).resolve().parents[1]
        ci = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
        body = ci["jobs"]["check"]["steps"][1]["run"]
        bash = (
            str(Path(os.environ["PROGRAMFILES"]) / "Git/bin/bash.exe")
            if sys.platform == "win32"
            else shutil.which("bash")
        )
        assert bash is not None
        result = subprocess.run(
            [bash, "-c", 'git() { printf "%s\\n" "$ACTUAL_SHA"; }\n' + body],
            cwd=tmp_path,
            env={**os.environ, "EXPECTED_SHA": "b" * 40, "ACTUAL_SHA": actual},
            capture_output=True,
            text=True,
            check=False,
        )
        assert (result.returncode == 0) == (actual == "b" * 40), result.stderr
