"""Verify original published packages for GitHub-only release repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path


class ReleaseRepair:
    """Recover original bytes without building, retagging or publishing packages."""

    REPOSITORY = "mikejhill/launchline"

    @staticmethod
    def gh(*arguments: str) -> str:
        """Execute bounded, explicit GitHub CLI arguments without a shell."""
        return subprocess.run(
            ["gh", *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        ).stdout

    @staticmethod
    def table(value: object) -> dict[str, object]:
        """Reject malformed JSON tables at the service boundary."""
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        if not all(isinstance(key, str) for key in value):
            raise ValueError("Expected string JSON keys")
        return {str(key): item for key, item in value.items()}

    @staticmethod
    def text(value: object) -> str:
        """Validate JSON text before using it as a package identity."""
        if not isinstance(value, str):
            raise ValueError("Expected JSON text")
        return value

    @staticmethod
    def sequence(value: object) -> list[object]:
        """Validate a JSON array without guessing its shape."""
        if not isinstance(value, list):
            raise ValueError("Expected a JSON array")
        return list(value)

    @classmethod
    def api(cls, path: str) -> dict[str, object]:
        """Read only fixed-repository API paths."""
        return cls.table(json.loads(cls.gh("api", f"repos/{cls.REPOSITORY}/{path}")))

    @classmethod
    def prepare(cls, directory: Path, version: str, run_id: str) -> str:
        """Require original source, successful build, registry bytes and provenance."""
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
            raise ValueError("Expected a stable published version")
        if re.fullmatch(r"[0-9]+", run_id) is None:
            raise ValueError("Expected the original numeric release run ID")
        source = cls.api(f"commits/v{version}")["sha"]
        if not isinstance(source, str) or re.fullmatch(r"[0-9a-f]{40}", source) is None:
            raise ValueError("Existing source tag is invalid")
        if (
            cls.table(cls.api(f"compare/{source}...main")["merge_base_commit"])["sha"]
            != source
        ):
            raise ValueError("Existing release source is not on main")
        run = cls.api(f"actions/runs/{run_id}")
        if (
            run["head_sha"] != source
            or run["head_branch"] != "main"
            or run["event"] != "push"
            or run["status"] != "completed"
            or run["path"] != ".github/workflows/release.yml"
        ):
            raise ValueError("Original artifact run does not match trusted source")
        jobs = [
            cls.table(job)
            for job in cls.sequence(
                cls.api(f"actions/runs/{run_id}/jobs?per_page=100")["jobs"]
            )
        ]
        required = [
            job
            for job in jobs
            if job["name"] in {"Build", "Attest tested artifacts"}
            or cls.text(job["name"]).startswith("Python (")
        ]
        if len(required) != 11 or any(
            job["conclusion"] != "success" for job in required
        ):
            raise ValueError(
                "Original matrix, build and attestation must have succeeded"
            )
        paths = [
            directory / "dist" / f"launchline-{version}{suffix}"
            for suffix in ("-py3-none-any.whl", ".tar.gz")
        ]
        hashes = {}
        for path in paths:
            if not 0 < path.stat().st_size <= 10 * 1024 * 1024:
                raise ValueError("Unexpected original artifact size")
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        with zipfile.ZipFile(paths[0]) as wheel:
            wheel_metadata = wheel.read(f"launchline-{version}.dist-info/METADATA")
        with tarfile.open(paths[1]) as sdist:
            metadata = sdist.extractfile(f"launchline-{version}/PKG-INFO")
            if metadata is None:
                raise ValueError("Missing original distribution metadata")
            source_metadata = metadata.read()
        for payload in (wheel_metadata, source_metadata):
            parsed = BytesParser().parsebytes(payload)
            if parsed["Name"] != "launchline" or parsed["Version"] != version:
                raise ValueError("Original package identity does not match version")
        with urllib.request.urlopen(
            f"https://pypi.org/pypi/launchline/{version}/json", timeout=30
        ) as response:
            registry = cls.table(json.load(response))
        published = [cls.table(item) for item in cls.sequence(registry["urls"])]
        if cls.table(registry["info"])["version"] != version or {
            item["filename"] for item in published
        } != set(hashes):
            raise ValueError("Published version has unexpected distribution identity")
        for item in published:
            if (
                item["yanked"]
                or cls.table(item["digests"])["sha256"]
                != hashes[cls.text(item["filename"])]
            ):
                raise ValueError("Published artifact differs or is yanked")
        attestations = {}
        for path in paths:
            attestations[path.name] = json.loads(
                cls.gh(
                    "attestation",
                    "verify",
                    str(path),
                    "--repo",
                    cls.REPOSITORY,
                    "--signer-workflow",
                    f"{cls.REPOSITORY}/.github/workflows/release.yml",
                    "--source-digest",
                    source,
                    "--source-ref",
                    "refs/heads/main",
                    "--deny-self-hosted-runners",
                    "--format",
                    "json",
                )
            )
            if not attestations[path.name]:
                raise ValueError("Original artifact provenance is missing")
        record = {"version": version, "source_sha": source, "sha256": hashes}
        manifest = directory / "release-manifest.json"
        if manifest.exists() and json.loads(manifest.read_text()) != record:
            raise ValueError("Original release manifest differs")
        manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        (directory / "SHA256SUMS").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in hashes.items()),
            encoding="utf-8",
        )
        notes = directory / "release-notes.md"
        if not notes.exists():
            notes.write_text(
                f"Verified published LaunchLine {version}.\n\nSource: {source}\n",
                encoding="utf-8",
            )
        (directory / "provenance-verification.json").write_text(
            json.dumps(attestations, indent=2), encoding="utf-8"
        )
        return source

    @classmethod
    def main(cls) -> None:
        """Emit verified repair inputs for a separate GitHub-only publisher."""
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("version")
        parser.add_argument("run_id")
        args = parser.parse_args()
        source = cls.prepare(Path("release"), args.version, args.run_id)
        output = os.environ.get("GITHUB_OUTPUT")
        if output is not None:
            with Path(output).open("a", encoding="utf-8") as stream:
                stream.write(f"source_sha={source}\n")
        sys.stdout.write(
            f"Verified published {args.version}, original run {args.run_id}, "
            f"source {source}.\n"
        )


if __name__ == "__main__":
    ReleaseRepair.main()
