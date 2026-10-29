"""Bounded execution of explicitly configured, trusted menu providers."""

from __future__ import annotations

import ctypes
import json
import logging
import math
import os
import signal
import subprocess
import sys
import threading
import time
from typing import IO

from launchline.config import ConfigLoader, EntryConfig, ProviderConfig
from launchline.exceptions import ConfigurationError, LaunchLineError

logger = logging.getLogger(__name__)
MAX_PROVIDER_BYTES = 1_048_576


class ProviderError(LaunchLineError):
    """A provider failed without replacing the last valid menu snapshot."""


class _BasicLimits(ctypes.Structure):
    """Windows JOBOBJECT_BASIC_LIMIT_INFORMATION ABI."""

    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", ctypes.c_uint32),
        ("minimum", ctypes.c_size_t),
        ("maximum", ctypes.c_size_t),
        ("active", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority", ctypes.c_uint32),
        ("scheduling", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    """Windows IO_COUNTERS ABI."""

    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_ops",
            "write_ops",
            "other_ops",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    """Windows JOBOBJECT_EXTENDED_LIMIT_INFORMATION ABI."""

    _fields_ = [
        ("basic", _BasicLimits),
        ("io", _IoCounters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t),
        ("peak_job", ctypes.c_size_t),
    ]


class ProcessTree:
    """Own a POSIX process group or Windows kill-on-close job for a provider."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        """Attach a trusted child to its cleanup boundary immediately after spawn."""
        self._process = process
        self._job: int | None = None
        if sys.platform != "win32":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel.SetInformationJobObject.restype = ctypes.c_int
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel.AssignProcessToJobObject.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        self._kernel = kernel
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "Cannot create provider job")
        self._job = job
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        child = kernel.OpenProcess(0x0101, False, process.pid)
        try:
            if (
                not child
                or not kernel.SetInformationJobObject(
                    job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
                or not kernel.AssignProcessToJobObject(job, child)
            ):
                raise OSError(
                    ctypes.get_last_error(), "Cannot contain provider process"
                )
        except OSError:
            self.close()
            raise
        finally:
            if child:
                kernel.CloseHandle(child)

    def close(self) -> None:
        """Terminate the owned group/job, including descendants still holding pipes."""
        if sys.platform == "win32":
            if self._job is not None:
                self._kernel.CloseHandle(self._job)
                self._job = None
            return
        for attempt in range(10):
            try:
                os.killpg(self._process.pid, signal.SIGKILL)
            except ProcessLookupError:
                logger.debug("Provider process group already exited")
                return
            except PermissionError:
                # Darwin can retain an all-zombie group briefly: killpg filters
                # zombies out, then reports EPERM when no live member was found.
                # The leader may not yet be waitable when that transition starts.
                # Reap it when possible, without treating persistent EPERM as a
                # successful cleanup or relaxing the process-group boundary.
                if sys.platform != "darwin" or attempt == 9:
                    raise
                self._process.poll()
                time.sleep(0.01)
            else:
                return


class _OutputCapture:
    """Drain one child pipe while enforcing a strict in-memory byte cap."""

    def __init__(self, pipe: IO[bytes]) -> None:
        """Store the owned read end without reading on the UI thread."""
        self.pipe = pipe
        self.data = bytearray()
        self.exceeded = threading.Event()
        self.finished = threading.Event()

    def read(self) -> None:
        """Stop retaining bytes at the cap and signal the supervising thread."""
        try:
            while chunk := self.pipe.read(8192):
                if len(self.data) + len(chunk) > MAX_PROVIDER_BYTES:
                    self.exceeded.set()
                    return
                self.data.extend(chunk)
        finally:
            self.finished.set()


class MenuProvider:
    """Execute bounded providers without a shell or terminal stdin."""

    def resolve(
        self, provider: ProviderConfig, *, depth: int
    ) -> tuple[EntryConfig, ...]:
        """Require successful bounded UTF-8 JSON containing an entries array."""
        try:
            payload = self._execute(provider)
            raw: object = json.loads(
                payload.decode("utf-8"),
                parse_constant=self._reject_constant,
                parse_float=self._finite_float,
                parse_int=self._integer,
            )
            self._validate_json(raw)
            table = ConfigLoader._table(raw, "provider output")
            if "entries" not in table:
                raise ConfigurationError("Provider output requires an entries array.")
            return ConfigLoader.parse_entries(
                table["entries"], depth=depth, max_entries=1000
            )
        except (
            OSError,
            ValueError,
            RecursionError,
            ConfigurationError,
        ) as error:
            raise ProviderError(f"Invalid provider result: {error}") from error

    @staticmethod
    def _reject_constant(token: str) -> float:
        """Reject non-JSON NaN/Infinity tokens rather than accepting extensions."""
        raise ConfigurationError(f"Non-finite JSON number: {token}")

    @staticmethod
    def _integer(token: str) -> int:
        """Reject magnitudes outside the native JSON parser's finite range."""
        MenuProvider._finite_float(token)
        return int(token)

    @staticmethod
    def _finite_float(token: str) -> float:
        """Reject exponent overflow consistently with the native JSON parser."""
        value = float(token)
        if not math.isfinite(value):
            raise ConfigurationError("JSON numeric overflow.")
        return value

    @staticmethod
    def _validate_json(value: object) -> None:
        """Bound container nesting and reject unpaired Unicode surrogates."""
        stack: list[tuple[object, int]] = [(value, 0)]
        while stack:
            item, depth = stack.pop()
            if isinstance(item, (list, dict)):
                if depth >= 64:
                    raise ConfigurationError(
                        "Provider JSON nesting exceeds 64 containers."
                    )
                if isinstance(item, dict):
                    stack.extend((key, depth + 1) for key in item)
                    stack.extend((child, depth + 1) for child in item.values())
                else:
                    stack.extend((child, depth + 1) for child in item)
            elif isinstance(item, str) and any(
                0xD800 <= ord(char) <= 0xDFFF for char in item
            ):
                raise ConfigurationError(
                    "Provider strings must contain Unicode scalars."
                )

    @staticmethod
    def _execute(provider: ProviderConfig) -> bytes:
        """Supervise a trusted child and always reap it and its cleanup boundary."""
        entry = provider.entry
        if entry.command.lower().endswith((".bat", ".cmd")):
            raise ProviderError(
                "Batch providers must explicitly invoke cmd.exe with argv."
            )
        environment = dict(os.environ)
        environment.update(
            {key: os.path.expanduser(value) for key, value in entry.env.items()}
        )
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        with subprocess.Popen(
            [entry.command, *entry.args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=entry.working_directory,
            env=environment,
            start_new_session=sys.platform != "win32",
            creationflags=flags,
        ) as process:
            tree = None
            capture = None
            reader = None
            try:
                tree = ProcessTree(process)
                if process.stdout is None:
                    raise ProviderError("Provider stdout is unavailable.")
                capture = _OutputCapture(process.stdout)
                reader = threading.Thread(target=capture.read, daemon=True)
                reader.start()
                deadline = time.monotonic() + provider.timeout_seconds
                while process.poll() is None:
                    if capture.exceeded.is_set():
                        raise ProviderError("Provider output exceeds 1048576 bytes.")
                    if time.monotonic() >= deadline:
                        raise ProviderError("Provider timed out.")
                    try:
                        process.wait(timeout=0.02)
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if tree is not None:
                    tree.close()
                if process.poll() is None:
                    process.kill()
                process.wait()
                if reader is not None:
                    reader.join(timeout=2)
            if capture is None or not capture.finished.is_set():
                raise ProviderError("Provider output did not close after cleanup.")
            if capture.exceeded.is_set():
                raise ProviderError("Provider output exceeds 1048576 bytes.")
            if process.returncode != 0:
                raise ProviderError(
                    f"Provider exited with status {process.returncode}."
                )
            return bytes(capture.data)
