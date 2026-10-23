"""Install the built wheel in isolation and test its actual console entry point."""

from __future__ import annotations

import json
import subprocess
import tempfile
import zipfile
from pathlib import Path


class PackageSmoke:
    """Validate distributions without publishing or touching the user's config."""

    @staticmethod
    def main() -> None:
        """Check metadata, packaged icon, CLI errors, and config resolution."""
        root = Path(__file__).resolve().parents[1]
        wheel = next((root / "dist").glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            assert "launchline/assets/launchline.ico" in archive.namelist()
        records = []
        with tempfile.TemporaryDirectory(prefix="launchline-wheel-") as temp:
            cwd = Path(temp)
            config = cwd / "config.toml"
            config.write_text(
                '[[entries]]\nname="safe"\ncommand="unused"', encoding="utf-8"
            )
            for args, expected in [
                (["--help"], 0),
                (["--icon-path"], 0),
                (["--config-path", "--config", str(config)], 0),
                (["--config-path", "--config", str(cwd / "missing.toml")], 1),
                (["--log-level", "INVALID"], 2),
            ]:
                result = subprocess.run(
                    [
                        "uv",
                        "tool",
                        "run",
                        "--isolated",
                        "--from",
                        str(wheel),
                        "launchline",
                        *args,
                    ],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                assert result.returncode == expected, (args, result.stderr)
                assert "Traceback" not in result.stderr, result.stderr
                if args == ["--icon-path"]:
                    assert Path(result.stdout.strip()).is_file(), result.stdout
                records.append({"args": args, "exit": result.returncode})
        (root / "docs/validation/package-smoke.json").write_text(
            json.dumps(records, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    PackageSmoke.main()
