"""Offline original-source, registry and provenance checks for GitHub-only repair."""

from __future__ import annotations

import hashlib
import io
import json
import runpy
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from tests.test_release_artifacts import TestReleaseArtifacts as ArchiveFixture


class OriginalRelease:
    """Intercept only GitHub/HTTP boundaries while retaining real archive parsing."""

    def __init__(self, directory: Path, scenario: str) -> None:
        self.scenario = scenario
        self.calls: list[tuple[str, ...]] = []
        self.directory = directory

    def gh(self, *args: str) -> str:
        """Serve exact trusted-run fixture responses and reject every mutation."""
        self.calls.append(args)
        source = "a" * 40
        if args[0] == "attestation":
            assert args[:2] == ("attestation", "verify")
            assert "--deny-self-hosted-runners" in args
            assert args[args.index("--source-digest") + 1] == source
            if self.scenario == "attestation-error":
                raise subprocess.CalledProcessError(1, args)
            return (
                "[]" if self.scenario == "missing-provenance" else '[{"verified":true}]'
            )
        assert args[0] == "api"
        endpoint = args[1]
        if "/commits/" in endpoint:
            return json.dumps(
                {"sha": "short" if self.scenario == "invalid-tag" else source}
            )
        if "/compare/" in endpoint:
            return json.dumps(
                {
                    "merge_base_commit": {
                        "sha": "b" * 40 if self.scenario == "not-main" else source
                    }
                }
            )
        if "/jobs?" in endpoint:
            names = [f"Python (fixture, {index})" for index in range(9)]
            names += ["Build", "Attest tested artifacts"]
            if self.scenario == "missing-matrix":
                names.pop(0)
            return json.dumps(
                {
                    "jobs": [
                        {
                            "name": name,
                            "conclusion": "failure"
                            if self.scenario == "failed-build" and name == "Build"
                            else "success",
                        }
                        for name in names
                    ]
                }
            )
        return json.dumps(
            {
                "head_sha": "b" * 40 if self.scenario == "wrong-run" else source,
                "head_branch": "main",
                "event": "push",
                "status": "completed",
                "path": ".github/workflows/ci.yml"
                if self.scenario == "wrong-workflow"
                else ".github/workflows/release.yml",
            }
        )

    def registry(self, _url: str, *, timeout: int) -> io.BytesIO:
        """Return published hashes for the actual local archives."""
        assert timeout == 30
        files = []
        for path in sorted((self.directory / "dist").iterdir()):
            files.append(
                {
                    "filename": path.name,
                    "yanked": self.scenario == "yanked",
                    "digests": {
                        "sha256": "different"
                        if self.scenario == "registry-conflict"
                        else hashlib.sha256(path.read_bytes()).hexdigest()
                    },
                }
            )
        if self.scenario == "unknown-file":
            files.append({"filename": "foreign.whl"})
        return io.BytesIO(
            json.dumps({"info": {"version": "0.4.1"}, "urls": files}).encode()
        )


class TestReleaseRepair:
    """Require original attested, published bytes before creating any repair payload."""

    @pytest.mark.parametrize(
        "scenario",
        [
            "valid",
            "invalid-tag",
            "not-main",
            "wrong-run",
            "wrong-workflow",
            "failed-build",
            "missing-matrix",
            "registry-conflict",
            "unknown-file",
            "yanked",
            "missing-provenance",
            "attestation-error",
            "manifest-conflict",
            "metadata",
        ],
    )
    def test_only_original_verified_release_becomes_repair_payload(
        self, tmp_path: Path, scenario: str
    ) -> None:
        """Reject source/run/registry conflicts without building or publishing."""
        ArchiveFixture._fixture(
            tmp_path, "0.4.0" if scenario == "metadata" else "0.4.1"
        )
        if scenario == "manifest-conflict":
            (tmp_path / "release-manifest.json").write_text("{}")
        root = Path(__file__).resolve().parents[1]
        helper = runpy.run_path(str(root / "scripts/repair_release.py"))[
            "ReleaseRepair"
        ]
        service = OriginalRelease(tmp_path, scenario)
        with (
            patch.object(helper, "gh", side_effect=service.gh),
            patch("urllib.request.urlopen", side_effect=service.registry),
        ):
            if scenario == "valid":
                assert helper.prepare(tmp_path, "0.4.1", "1234") == "a" * 40
                original = (tmp_path / "release-manifest.json").read_bytes()
                assert helper.prepare(tmp_path, "0.4.1", "1234") == "a" * 40
                assert (tmp_path / "release-manifest.json").read_bytes() == original
            else:
                with pytest.raises((ValueError, subprocess.CalledProcessError)):
                    helper.prepare(tmp_path, "0.4.1", "1234")
        assert all(call[0] in {"api", "attestation"} for call in service.calls)
        assert all("--method" not in call for call in service.calls)

    def test_repair_workflow_cannot_build_publish_packages_or_retag(self) -> None:
        """Isolate GitHub mutation after read-only verification."""
        root = Path(__file__).resolve().parents[1]
        workflow = yaml.safe_load(
            (root / ".github/workflows/repair-github-release.yml").read_text()
        )
        assert (
            workflow["on"]["workflow_dispatch"]["inputs"]["verify-only"]["default"]
            is True
        )
        assert workflow["permissions"] == {"contents": "read"}
        assert workflow["jobs"]["prepare"]["permissions"]["contents"] == "read"
        publisher = workflow["jobs"]["github-release"]
        assert "!inputs.verify-only" in publisher["if"]
        assert "github.actor == 'mikejhill'" in publisher["if"]
        assert "github.triggering_actor == 'mikejhill'" in publisher["if"]
        assert "id-token" not in publisher["permissions"]
        assert not any(
            "checkout@" in step.get("uses", "") for step in publisher["steps"]
        )
        body = publisher["steps"][-1]["run"]
        for forbidden in (
            "git/refs",
            "--clobber",
            "uv build",
            "pypi-publish",
            "git tag",
        ):
            assert forbidden not in body
        normal = yaml.safe_load((root / ".github/workflows/release.yml").read_text())
        config = json.loads((root / "release-please-config.json").read_text())
        assert config["draft"] is True
        assert config["force-tag-creation"] is True
        assert "pypi" in normal["jobs"]["github-release"]["needs"]
        assert "attest" in normal["jobs"]["pypi"]["needs"]
        assert "github-release" not in normal["jobs"]["pypi"]["needs"]
