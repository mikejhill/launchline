"""Validate versioned distributions and record their reviewed source and hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path


class ReleaseArtifacts:
    """Keep tag, reviewed version, package metadata and release assets consistent."""

    @staticmethod
    def validate_distributions(directory: Path, version: str) -> tuple[str, str]:
        """Validate actual build output, allowing only uv's known VCS sidecar."""
        wheel_name = f"launchline-{version}-py3-none-any.whl"
        sdist_name = f"launchline-{version}.tar.gz"
        contents = {path.name: path for path in directory.iterdir()}
        marker = contents.pop(".gitignore", None)
        if marker is not None and (
            marker.is_symlink()
            or not marker.is_file()
            or marker.read_bytes() not in {b"*", b"*\n", b"*\r\n"}
        ):
            raise ValueError("Unexpected build-directory .gitignore")
        if set(contents) != {wheel_name, sdist_name}:
            raise ValueError("Release must contain exactly its wheel and sdist")
        with zipfile.ZipFile(directory / wheel_name) as wheel:
            wheel_metadata = wheel.read(f"launchline-{version}.dist-info/METADATA")
        with tarfile.open(directory / sdist_name) as sdist:
            metadata = sdist.extractfile(f"launchline-{version}/PKG-INFO")
            if metadata is None:
                raise ValueError("Source distribution metadata is missing")
            sdist_metadata = metadata.read()
        for content in (wheel_metadata, sdist_metadata):
            parsed = BytesParser().parsebytes(content)
            if parsed["Name"] != "launchline" or parsed["Version"] != version:
                raise ValueError("Distribution metadata does not match its version")
        return wheel_name, sdist_name

    @staticmethod
    def prepare(root: Path, version: str, revision: str) -> None:
        """Reject inconsistent inputs before emitting publication evidence."""
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
            raise ValueError("Release version must be stable semantic versioning")
        if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            raise ValueError("Release source must be an immutable commit")
        manifest = json.loads((root / ".release-please-manifest.json").read_text())
        if manifest != {".": version}:
            raise ValueError("Reviewed release manifest does not match tag version")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        heading = re.search(
            rf"^## \[?{re.escape(version)}(?:\]|\s|\().*$",
            changelog,
            re.MULTILINE,
        )
        if heading is None:
            raise ValueError("Reviewed changelog has no matching release section")
        notes = changelog[heading.start() :]
        following = re.search(r"\n## ", notes)
        if following is not None:
            notes = notes[: following.start()]
        directory = root / "dist"
        wheel_name, sdist_name = ReleaseArtifacts.validate_distributions(
            directory, version
        )
        hashes = {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in sorted((wheel_name, sdist_name))
        }
        (root / "release-manifest.json").write_text(
            json.dumps(
                {"version": version, "source_sha": revision, "sha256": hashes}, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        (root / "SHA256SUMS").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in hashes.items()),
            encoding="utf-8",
        )
        (root / "release-notes.md").write_text(
            f"Built from reviewed main commit {revision}\n\n{notes.strip()}\n",
            encoding="utf-8",
        )

    @classmethod
    def main(cls) -> None:
        """Prepare same-run release evidence from the tested working tree."""
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("version", nargs="?")
        parser.add_argument("revision", nargs="?")
        parser.add_argument("--check-build", action="store_true")
        args = parser.parse_args()
        root = Path.cwd()
        if args.check_build:
            if args.version is not None or args.revision is not None:
                parser.error("--check-build does not accept release arguments")
            wheels = list((root / "dist").glob("launchline-*-py3-none-any.whl"))
            if len(wheels) != 1:
                parser.error("Build must contain exactly one LaunchLine wheel")
            version = (
                wheels[0]
                .name.removeprefix("launchline-")
                .removesuffix("-py3-none-any.whl")
            )
            cls.validate_distributions(root / "dist", version)
            print(f"Validated wheel and sdist for {version}")
        else:
            if args.version is None or args.revision is None:
                parser.error("A release requires its version and immutable revision")
            cls.prepare(root, args.version, args.revision)


if __name__ == "__main__":
    ReleaseArtifacts.main()
