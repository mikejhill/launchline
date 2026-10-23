"""Install the built wheel in isolation and test its actual console entry point."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from importlib.metadata import version as installed_version
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
            installed = cwd / "installed"
            subprocess.run(
                ["uv", "venv", "--python", sys.executable, str(installed)],
                check=True,
                timeout=60,
            )
            scripts = installed / ("Scripts" if sys.platform == "win32" else "bin")
            interpreter = scripts / (
                "python.exe" if sys.platform == "win32" else "python"
            )
            pty_package = "pywinpty" if sys.platform == "win32" else "pexpect"
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(interpreter),
                    str(wheel),
                    f"pytest=={installed_version('pytest')}",
                    f"{pty_package}=={installed_version(pty_package)}",
                ],
                check=True,
                timeout=120,
            )
            environment = {
                key: value
                for key, value in os.environ.items()
                if key != "LAUNCHLINE_RUST"
            }
            subprocess.run(
                [
                    str(interpreter),
                    "-m",
                    "pytest",
                    str(root / "tests/test_terminal_e2e.py"),
                    "-o",
                    "addopts=",
                    "-q",
                ],
                cwd=cwd,
                env=environment,
                check=True,
                timeout=180,
            )
            records.append({"installed_terminal_suite": "passed"})
        (root / "docs/validation/package-smoke.json").write_text(
            json.dumps(records, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    PackageSmoke.main()
