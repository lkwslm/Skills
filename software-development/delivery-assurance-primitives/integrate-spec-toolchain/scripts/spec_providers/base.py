"""Shared primitives for strict provider adapters."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
import time
import unicodedata
import signal
from typing import Any


SCHEMA_VERSION = "1.0"
VERSION_PATTERN = re.compile(r"(?<![A-Za-z0-9])v?(\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?)(?![A-Za-z0-9])")
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
MAX_CLI_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_JSONL_RECORDS = 100_000
MAX_PROVIDER_FILES = 100_000
MAX_RUNTIME_FILES = 100_000
MAX_RUNTIME_FILE_BYTES = 512 * 1024 * 1024
MAX_INTEGER_DIGITS = 1000


def _create_windows_job(process: subprocess.Popen[Any]) -> int:
    """Atomically bind a suspended process to a kill-on-close Job, then resume it."""
    import ctypes
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class ThreadEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                    ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD)]

    kernel = ctypes.windll.kernel32
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError("CreateJobObjectW failed")
    info = ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    try:
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError("SetInformationJobObject failed")
        if not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):
            raise OSError("AssignProcessToJobObject failed")
        snapshot = kernel.CreateToolhelp32Snapshot(0x00000004, 0)
        invalid = wintypes.HANDLE(-1).value
        if snapshot == invalid:
            raise OSError("CreateToolhelp32Snapshot failed")
        try:
            entry = ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel.Thread32First(snapshot, ctypes.byref(entry))
            while found and entry.th32OwnerProcessID != process.pid:
                found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
            if not found:
                raise OSError("suspended process thread not found")
            thread = kernel.OpenThread(0x0002, False, entry.th32ThreadID)
            if not thread:
                raise OSError("OpenThread failed")
            try:
                if kernel.ResumeThread(thread) == 0xFFFFFFFF:
                    raise OSError("ResumeThread failed")
            finally:
                kernel.CloseHandle(thread)
        finally:
            kernel.CloseHandle(snapshot)
        return int(job)
    except Exception:
        kernel.TerminateJobObject(job, 1)
        kernel.CloseHandle(job)
        raise


@dataclass
class ProviderError(Exception):
    code: str
    message: str
    exit_code: int = 1

    def __str__(self) -> str:
        return self.message


def canonical_json(value: Any) -> bytes:
    def normalize(item: Any, where: str = "$") -> Any:
        if item is None or isinstance(item, bool) or isinstance(item, int):
            return item
        if isinstance(item, float):
            raise ValueError(f"floating-point values are forbidden at {where}")
        if isinstance(item, str):
            return unicodedata.normalize("NFC", item)
        if isinstance(item, list):
            return [normalize(child, where + "[]") for child in item]
        if isinstance(item, dict):
            result: dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"object keys must be strings at {where}")
                normalized_key = unicodedata.normalize("NFC", key)
                if normalized_key in result:
                    raise ValueError(f"object keys collide after NFC normalization at {where}")
                result[normalized_key] = normalize(child, where + "." + normalized_key)
            return result
        raise ValueError(f"unsupported value type at {where}: {type(item).__name__}")

    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def strict_json(text: str) -> Any:
    def bounded_int(value: str) -> int:
        if len(value.lstrip("+-")) > MAX_INTEGER_DIGITS:
            raise ValueError("integer exceeds the provider protocol digit limit")
        return int(value)

    return json.loads(
        text,
        object_pairs_hook=_unique_object,
        parse_int=bounded_int,
        parse_float=lambda value: (_ for _ in ()).throw(ValueError(f"floating-point JSON numbers are not accepted: {value}")),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON constant: {value}")),
    )


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hash_file(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ProviderError("PROVIDER_LAYOUT_INVALID", f"provider artifact is missing, non-regular, or too large: {path}", 2)
        return hash_bytes(path.read_bytes())
    except (OSError, UnicodeDecodeError) as exc:
        raise ProviderError("PROVIDER_LAYOUT_INVALID", f"cannot read provider artifact {path}: {exc}", 2) from exc


def hash_runtime_file(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size > MAX_RUNTIME_FILE_BYTES:
            raise ProviderError("PROVIDER_CLI_UNPINNED", f"provider runtime file is missing, non-regular, or too large: {path}", 3)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise ProviderError("PROVIDER_CLI_UNPINNED", f"cannot read provider runtime file {path}: {exc}", 3) from exc


def hash_json(value: Any) -> str:
    return hash_bytes(canonical_json(value))


def load_json(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ProviderError("PROVIDER_LAYOUT_INVALID", f"provider JSON is missing, non-regular, or too large: {path}", 2)
        value = strict_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ProviderError("PROVIDER_LAYOUT_INVALID", f"cannot read {path}: {exc}", 2) from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProviderError("PROVIDER_DATA_INVALID", f"invalid JSON in {path}: {exc}", 2) from exc
    if not isinstance(value, dict):
        raise ProviderError("PROVIDER_DATA_INVALID", f"provider document must be an object: {path}", 2)
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ProviderError("PROVIDER_LAYOUT_INVALID", f"provider JSONL is missing, non-regular, or too large: {path}", 2)
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ProviderError("PROVIDER_LAYOUT_INVALID", f"cannot read {path}: {exc}", 2) from exc
    if not lines:
        raise ProviderError("PROVIDER_DATA_INVALID", f"provider JSONL log is empty: {path}", 2)
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if line_number > MAX_JSONL_RECORDS:
            raise ProviderError("PROVIDER_DATA_INVALID", f"provider JSONL exceeds {MAX_JSONL_RECORDS} records: {path}", 2)
        try:
            value = strict_json(line)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError("PROVIDER_DATA_INVALID", f"invalid JSONL at {path}:{line_number}: {exc}", 2) from exc
        if not isinstance(value, dict):
            raise ProviderError("PROVIDER_DATA_INVALID", f"JSONL record must be an object at {path}:{line_number}", 2)
        records.append(value)
    return records


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ProviderError("PROVIDER_LAYOUT_INVALID", f"provider YAML is missing, non-regular, or too large: {path}", 2)
        import yaml
    except ImportError as exc:
        raise ProviderError("DEPENDENCY_UNAVAILABLE", "PyYAML is required for OpenSpec configuration", 3) from exc
    try:
        class UniqueSafeLoader(yaml.SafeLoader):
            node_count = 0
            def compose_node(self, parent: Any, index: Any) -> Any:
                if self.check_event(yaml.events.AliasEvent):
                    raise yaml.YAMLError("YAML aliases are not accepted")
                self.node_count += 1
                if self.node_count > MAX_JSONL_RECORDS:
                    raise yaml.YAMLError(f"YAML document exceeds {MAX_JSONL_RECORDS} nodes")
                return super().compose_node(parent, index)

        def construct_mapping(loader: Any, node: Any, deep: bool = False) -> dict[Any, Any]:
            loader.flatten_mapping(node)
            result: dict[Any, Any] = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if key in result:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping", node.start_mark,
                        f"found duplicate key {key!r}", key_node.start_mark,
                    )
                result[key] = loader.construct_object(value_node, deep=deep)
            return result

        def construct_bounded_int(loader: Any, node: Any) -> int:
            digits = node.value.replace("_", "").lstrip("+-")
            if len(digits) > MAX_INTEGER_DIGITS:
                raise yaml.YAMLError(f"YAML integer exceeds {MAX_INTEGER_DIGITS} digits")
            return loader.construct_yaml_int(node)

        UniqueSafeLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            construct_mapping,
        )
        UniqueSafeLoader.add_constructor("tag:yaml.org,2002:int", construct_bounded_int)
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueSafeLoader)
    except (OSError, UnicodeDecodeError) as exc:
        raise ProviderError("PROVIDER_LAYOUT_INVALID", f"cannot read {path}: {exc}", 2) from exc
    except yaml.YAMLError as exc:
        raise ProviderError("PROVIDER_DATA_INVALID", f"invalid YAML in {path}: {exc}", 2) from exc
    def reject_float(item: Any) -> None:
        if isinstance(item, float):
            raise ProviderError("PROVIDER_DATA_INVALID", f"floating-point YAML numbers are not accepted: {path}", 2)
        if isinstance(item, dict):
            for child in item.values(): reject_float(child)
        elif isinstance(item, list):
            for child in item: reject_float(child)
        elif isinstance(item, int) and len(str(abs(item))) > MAX_INTEGER_DIGITS:
            raise ProviderError("PROVIDER_DATA_INVALID", f"integer exceeds the provider digit limit: {path}", 2)
    reject_float(value)
    if not isinstance(value, dict):
        raise ProviderError("PROVIDER_DATA_INVALID", f"provider document must be an object: {path}", 2)
    return value


def confined_relative(repo: Path, path: Path) -> str:
    try:
        resolved_repo = repo.resolve(strict=True)
        current = path
        while True:
            if current.exists():
                metadata = current.lstat()
                if current.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                    raise ProviderError("PROVIDER_LAYOUT_INVALID", f"provider path contains a link: {path}", 2)
            if current == resolved_repo or current.parent == current:
                break
            current = current.parent
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(resolved_repo)
    except (OSError, ValueError) as exc:
        raise ProviderError("PROVIDER_LAYOUT_INVALID", f"provider path escapes the repository or does not exist: {path}", 1) from exc
    return relative.as_posix()


class ProviderAdapter:
    provider: str
    executable_name: str
    version_args: tuple[str, ...]
    adapter_version = "1.0"

    def __init__(self, repo: Path, executable_path: Path, executable_sha256: str, manifest_path: Path, manifest_sha256: str, interpreter_path: Path | None = None, interpreter_sha256: str | None = None, entrypoint_path: Path | None = None, entrypoint_sha256: str | None = None):
        self.repo = repo.resolve()
        if (not executable_path.is_absolute() or not manifest_path.is_absolute()
                or not re.fullmatch(r"[0-9a-f]{64}", executable_sha256)
                or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256)):
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider CLI requires absolute paths and lowercase SHA-256 pins", 3)
        try:
            self.executable_path = executable_path.resolve(strict=True)
        except OSError as exc:
            raise ProviderError("PROVIDER_CLI_UNAVAILABLE", f"cannot resolve provider CLI: {exc}", 3) from exc
        try:
            self.executable_path.relative_to(self.repo)
        except ValueError:
            pass
        else:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider CLI must not come from the untrusted repository", 3)
        if self.executable_path.parent == Path.cwd().resolve():
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider CLI must not come from the process current directory", 3)
        if self.executable_path.suffix.lower() in {".bat", ".cmd", ".ps1", ".py", ".pyw", ".sh"}:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider CLI must be a directly executable native binary", 3)
        try:
            with self.executable_path.open("rb") as stream:
                magic = stream.read(4)
        except OSError as exc:
            raise ProviderError("PROVIDER_CLI_UNAVAILABLE", f"cannot inspect provider CLI format: {exc}", 3) from exc
        if magic.startswith(b"#!") or (os.name == "nt" and not magic.startswith(b"MZ")) or (os.name != "nt" and not (magic.startswith(b"\x7fELF") or magic in {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"})):
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider CLI must use the native executable format for this platform", 3)
        if (interpreter_path is None) != (interpreter_sha256 is None) or (entrypoint_path is None) != (entrypoint_sha256 is None):
            raise ProviderError("PROVIDER_CLI_UNPINNED", "interpreter mode requires pinned interpreter and entrypoint pairs", 3)
        if entrypoint_path is not None and interpreter_path is None:
            interpreter_path, interpreter_sha256 = executable_path, executable_sha256
        try:
            self.interpreter_path = interpreter_path.resolve(strict=True) if interpreter_path is not None else None
            self.entrypoint_path = entrypoint_path.resolve(strict=True) if entrypoint_path is not None else None
        except OSError as exc:
            raise ProviderError("PROVIDER_CLI_UNAVAILABLE", f"cannot resolve provider interpreter or entrypoint: {exc}", 3) from exc
        self.interpreter_sha256 = interpreter_sha256
        self.entrypoint_sha256 = entrypoint_sha256
        self.command_prefix: tuple[str, ...] = ()
        if self.interpreter_path is not None and self.entrypoint_path is not None:
            if not re.fullmatch(r"[0-9a-f]{64}", str(interpreter_sha256)) or not re.fullmatch(r"[0-9a-f]{64}", str(entrypoint_sha256)):
                raise ProviderError("PROVIDER_CLI_UNPINNED", "interpreter and entrypoint require lowercase SHA-256 pins", 3)
            self.command_prefix = (str(self.entrypoint_path),)
        try:
            self.manifest_path = manifest_path.resolve(strict=True)
        except OSError as exc:
            raise ProviderError("PROVIDER_CLI_UNAVAILABLE", f"cannot resolve provider runtime manifest: {exc}", 3) from exc
        if self.manifest_path.parent == Path.cwd().resolve() or self.manifest_path == self.executable_path:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider runtime manifest must be a separate trusted file", 3)
        self.manifest_sha256 = manifest_sha256
        self.executable_sha256 = executable_sha256
        self._verify_runtime_manifest()
        self.runtime: dict[str, Any] = {
            "executable": self.executable_name,
            "resolved_path": str(self.executable_path),
            "sha256": executable_sha256,
            "version_args": list(self.version_args),
            "observed_version": None,
            "manifest": str(self.manifest_path),
            "manifest_sha256": manifest_sha256,
        }
        if self.interpreter_path is not None:
            self.runtime.update({"interpreter": str(self.interpreter_path), "interpreter_sha256": self.interpreter_sha256, "entrypoint": str(self.entrypoint_path), "entrypoint_sha256": self.entrypoint_sha256})

    def _verify_runtime_manifest(self) -> None:
        if hash_file(self.manifest_path) != self.manifest_sha256:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider runtime manifest content differs from its pinned SHA-256", 3)
        manifest = load_json(self.manifest_path)
        if set(manifest) != {"schema_version", "root", "files"} or manifest["schema_version"] != "1.0" or not isinstance(manifest["root"], str) or not isinstance(manifest["files"], dict) or not manifest["files"]:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider runtime manifest schema is invalid", 3)
        root = Path(manifest["root"])
        try:
            metadata = root.lstat()
            if root.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                raise ProviderError("PROVIDER_CLI_UNPINNED", "provider runtime root must not be a link", 3)
            root = root.resolve(strict=True)
            root.relative_to(self.repo)
        except ValueError:
            pass
        except OSError as exc:
            raise ProviderError("PROVIDER_CLI_UNPINNED", f"provider runtime root cannot be resolved: {exc}", 3) from exc
        else:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider runtime root must be outside the repository", 3)
        expected = manifest["files"]
        if len(expected) > MAX_RUNTIME_FILES:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider runtime manifest contains too many files", 3)
        actual: dict[str, str] = {}
        for path in root.rglob("*"):
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise ProviderError("PROVIDER_CLI_UNPINNED", f"cannot inspect provider runtime tree: {exc}", 3) from exc
            if path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)) or not path.is_file():
                if path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                    raise ProviderError("PROVIDER_CLI_UNPINNED", "provider runtime tree contains a link", 3)
                continue
            relative = path.relative_to(root).as_posix()
            actual[relative] = hash_runtime_file(path)
        if actual != expected:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider runtime tree differs from its pinned manifest", 3)
        try:
            executable_relative = self.executable_path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider executable is outside its pinned runtime root", 3) from exc
        if expected.get(executable_relative) != self.executable_sha256:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider executable is not pinned by the runtime manifest", 3)
        if self.interpreter_path is not None and self.entrypoint_path is not None:
            for path, digest, label in ((self.interpreter_path, self.interpreter_sha256, "interpreter"), (self.entrypoint_path, self.entrypoint_sha256, "entrypoint")):
                try:
                    relative = path.relative_to(root).as_posix()
                except ValueError as exc:
                    raise ProviderError("PROVIDER_CLI_UNPINNED", f"provider {label} is outside its pinned runtime root", 3) from exc
                if expected.get(relative) != digest:
                    raise ProviderError("PROVIDER_CLI_UNPINNED", f"provider {label} is not pinned by the runtime manifest", 3)

    def require_runtime(self) -> str:
        self._verified_executable()
        output = self.run_text(self.version_args)
        match = VERSION_PATTERN.search(output)
        if match is None:
            raise ProviderError("PROVIDER_VERSION_INVALID", f"provider CLI returned no parseable version: {self.executable_name}")
        self.runtime["observed_version"] = match.group(1)
        return match.group(1)

    def run_text(self, args: tuple[str, ...]) -> str:
        resolved = self._verified_executable()
        try:
            process = subprocess.Popen(
                [resolved, *self.command_prefix, *args], cwd=self.repo, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                env={key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT"}},
                start_new_session=(os.name == "posix"),
                creationflags=((getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | 0x00000004) if os.name == "nt" else 0),
            )
            process_group = os.getpgid(process.pid) if os.name == "posix" else None
            job_handle = None
            if os.name == "nt":
                import ctypes
                try:
                    job_handle = _create_windows_job(process)
                except OSError:
                    process.kill(); process.wait()
                    raise ProviderError("PROVIDER_CLI_FAILED", "cannot assign provider CLI to a Windows job", 3)
            stdout_data = bytearray(); stderr_data = bytearray(); exceeded = threading.Event()

            def drain(stream: Any, buffer: bytearray) -> None:
                while True:
                    chunk = stream.read(64 * 1024)
                    if not chunk:
                        return
                    if len(buffer) + len(chunk) > MAX_CLI_OUTPUT_BYTES:
                        exceeded.set()
                        return
                    buffer.extend(chunk)

            out_thread = threading.Thread(target=drain, args=(process.stdout, stdout_data), daemon=True)
            err_thread = threading.Thread(target=drain, args=(process.stderr, stderr_data), daemon=True)
            out_thread.start(); err_thread.start()
            deadline = time.monotonic() + 10
            while process.poll() is None:
                if exceeded.is_set() or time.monotonic() >= deadline:
                    if os.name == "nt":
                        ctypes.windll.kernel32.TerminateJobObject(job_handle, 1)
                    else:
                        os.killpg(process_group, signal.SIGKILL)
                    process.kill(); process.wait(); out_thread.join(1); err_thread.join(1)
                    if out_thread.is_alive() or err_thread.is_alive():
                        process.stdout.close(); process.stderr.close()
                    if exceeded.is_set():
                        if job_handle: ctypes.windll.kernel32.CloseHandle(job_handle)
                        raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", "provider CLI output exceeds the 4 MiB limit")
                    if job_handle: ctypes.windll.kernel32.CloseHandle(job_handle)
                    raise ProviderError("PROVIDER_CLI_FAILED", "provider CLI timed out", 3)
                time.sleep(0.02)
            remaining = max(0.0, deadline - time.monotonic())
            out_thread.join(remaining)
            err_thread.join(max(0.0, deadline - time.monotonic()))
            if out_thread.is_alive() or err_thread.is_alive():
                if os.name == "nt":
                    ctypes.windll.kernel32.TerminateJobObject(job_handle, 1)
                else:
                    os.killpg(process_group, signal.SIGKILL)
                process.kill(); process.wait()
                if job_handle: ctypes.windll.kernel32.CloseHandle(job_handle)
                process.stdout.close(); process.stderr.close()
                raise ProviderError("PROVIDER_CLI_FAILED", "provider CLI left descendant processes holding output pipes", 3)
            if job_handle: ctypes.windll.kernel32.CloseHandle(job_handle)
            if exceeded.is_set():
                raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", "provider CLI output exceeds the 4 MiB limit")
            returncode = process.returncode
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProviderError("PROVIDER_CLI_FAILED", f"provider CLI failed: {exc}", 3) from exc
        if returncode != 0:
            diagnostic = bytes(stderr_data).decode("utf-8", "replace").strip() or bytes(stdout_data).decode("utf-8", "replace").strip() or f"exit {returncode}"
            raise ProviderError("PROVIDER_CLI_FAILED", f"provider CLI failed: {diagnostic}")
        try:
            output = bytes(stdout_data).decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"provider CLI stdout is not strict UTF-8: {exc}") from exc
        if not output:
            raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", "provider CLI returned empty stdout")
        return output

    def _verified_executable(self) -> str:
        self._verify_runtime_manifest()
        if not self.executable_path.is_file() or hash_runtime_file(self.executable_path) != self.executable_sha256:
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider CLI content differs from its pinned SHA-256", 3)
        if self.interpreter_path is not None and (not self.interpreter_path.is_file() or hash_runtime_file(self.interpreter_path) != self.interpreter_sha256):
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider interpreter content differs from its pinned SHA-256", 3)
        if self.entrypoint_path is not None and (not self.entrypoint_path.is_file() or hash_runtime_file(self.entrypoint_path) != self.entrypoint_sha256):
            raise ProviderError("PROVIDER_CLI_UNPINNED", "provider entrypoint content differs from its pinned SHA-256", 3)
        return str(self.executable_path)

    def run_json(self, args: tuple[str, ...]) -> dict[str, Any]:
        output = self.run_text(args)
        try:
            value = strict_json(output)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"provider CLI returned invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", "provider CLI JSON output must be an object")
        return value

    def finalize_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        profile["profile_hash"] = hash_json({key: value for key, value in profile.items() if key != "profile_hash"})
        return profile

    def detect(self) -> dict[str, Any]:
        raise NotImplementedError
