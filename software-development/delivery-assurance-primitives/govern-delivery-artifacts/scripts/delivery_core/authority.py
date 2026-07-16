"""Pinned authority resolution and typed content digests."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
import time
import signal
import stat
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


class AuthorityError(ValueError):
    """Authority or digest cannot be resolved exactly."""


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
CANONICALIZATIONS = {"raw-v1", "utf8-nfc-lf-v1", "delivery-json-v1"}
MAX_AUTHORITY_OUTPUT_BYTES = 50 * 1024 * 1024
MAX_GIT_RUNTIME_FILE_BYTES = 512 * 1024 * 1024
MAX_GIT_RUNTIME_FILES = 100_000


def _create_windows_job(process: subprocess.Popen[Any]) -> int:
    import ctypes
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

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
                    ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG), ("dwFlags", wintypes.DWORD)]

    kernel = ctypes.windll.kernel32
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError("CreateJobObjectW failed")
    info = ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = 0x00002000
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
            entry = ThreadEntry(); entry.dwSize = ctypes.sizeof(entry)
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
        kernel.TerminateJobObject(job, 1); kernel.CloseHandle(job)
        raise


def _canonical_json_bytes(value: Any) -> bytes:
    from .canonical import canonical_json_bytes

    return canonical_json_bytes(value)


def canonicalize(data: bytes, scheme: str) -> bytes:
    if scheme == "raw-v1":
        return data
    if scheme == "utf8-nfc-lf-v1":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AuthorityError("utf8-nfc-lf-v1 requires UTF-8 input") from exc
        text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
        return text.encode("utf-8")
    if scheme == "delivery-json-v1":
        try:
            from .canonical import loads_strict

            return _canonical_json_bytes(loads_strict(data))
        except (UnicodeDecodeError, ValueError) as exc:
            raise AuthorityError("delivery-json-v1 requires canonicalizable UTF-8 JSON") from exc
    raise AuthorityError(f"unknown canonicalization: {scheme}")


def digest_bytes(data: bytes, canonicalization: str = "raw-v1") -> dict[str, str]:
    material = canonicalize(data, canonicalization)
    return {
        "algorithm": "sha256",
        "canonicalization": canonicalization,
        "value": hashlib.sha256(material).hexdigest(),
    }


def validate_digest(value: Mapping[str, Any]) -> None:
    if set(value) != {"algorithm", "canonicalization", "value"}:
        raise AuthorityError("digest must contain exactly algorithm, canonicalization, and value")
    if value["algorithm"] != "sha256":
        raise AuthorityError("only sha256 digests are supported")
    if value["canonicalization"] not in CANONICALIZATIONS:
        raise AuthorityError(f"unknown canonicalization: {value['canonicalization']}")
    if not isinstance(value["value"], str) or not _HEX64.fullmatch(value["value"]):
        raise AuthorityError("digest value must be 64 lowercase hexadecimal characters")


def verify_digest(data: bytes, expected: Mapping[str, Any]) -> None:
    validate_digest(expected)
    actual = digest_bytes(data, str(expected["canonicalization"]))
    if actual != dict(expected):
        raise AuthorityError(f"authority digest mismatch: expected {expected['value']}, got {actual['value']}")


def _select_provider_content(data: bytes, selector: Mapping[str, Any]) -> bytes:
    if set(selector) != {"kind", "task_id"} or selector.get("kind") != "openspec-task-v1":
        raise AuthorityError("provider content selector is unsupported")
    task_id = selector.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise AuthorityError("provider task selector requires a task ID")
    try:
        text = unicodedata.normalize("NFC", data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n"))
    except UnicodeDecodeError as exc:
        raise AuthorityError("openspec-task-v1 requires UTF-8 input") from exc
    pattern = re.compile(r"^- \[([ xX])\] ([A-Za-z0-9][A-Za-z0-9._-]*)\s+(.+?)\s*$")
    matches = [match for line in text.splitlines() if (match := pattern.fullmatch(line)) and match.group(2) == task_id]
    if len(matches) != 1:
        raise AuthorityError(f"provider task selector must resolve exactly once: {task_id}")
    return f"- [ ] {task_id} {matches[0].group(3)}\n".encode("utf-8")


def _safe_git_path(raw: Any) -> str:
    if not isinstance(raw, str) or not raw or "\\" in raw or any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise AuthorityError("authority path must be a non-empty POSIX relative path")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AuthorityError("authority path must not be absolute or contain traversal")
    return path.as_posix()


def _hash_runtime_file(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_GIT_RUNTIME_FILE_BYTES:
            raise AuthorityError(f"Git runtime file is missing, non-regular, or too large: {path}")
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError as exc:
        raise AuthorityError(f"cannot read Git runtime file {path}: {exc}") from exc


def _trusted_git_executable(repo: Path, executable: Path | None, expected_sha256: str | None, manifest_path: Path | None, manifest_sha256: str | None) -> Path:
    if executable is None or expected_sha256 is None or manifest_path is None or manifest_sha256 is None:
        raise AuthorityError("trusted Git requires executable and runtime manifest paths with lowercase SHA-256 pins")
    if not executable.is_absolute() or not manifest_path.is_absolute() or not _HEX64.fullmatch(expected_sha256) or not _HEX64.fullmatch(manifest_sha256):
        raise AuthorityError("trusted Git requires executable and runtime manifest paths with lowercase SHA-256 pins")
    try:
        resolved = executable.resolve(strict=True)
    except OSError as exc:
        raise AuthorityError(f"trusted Git executable cannot be resolved: {exc}") from exc
    if not resolved.is_file():
        raise AuthorityError("trusted Git executable is not a regular file")
    if resolved.suffix.lower() in {".bat", ".cmd"}:
        raise AuthorityError("batch-file Git shims are not accepted")
    for untrusted in (repo.resolve(), Path.cwd().resolve()):
        try:
            resolved.relative_to(untrusted)
        except ValueError:
            continue
        raise AuthorityError("trusted Git executable must not be inside the repository or process current directory")
    actual = _hash_runtime_file(resolved)
    if actual != expected_sha256:
        raise AuthorityError("trusted Git executable content differs from its pinned SHA-256")
    from .canonical import loads_strict, read_bounded
    try:
        manifest = manifest_path.resolve(strict=True)
        if _hash_runtime_file(manifest) != manifest_sha256:
            raise AuthorityError("trusted Git runtime manifest differs from its pinned SHA-256")
        document = loads_strict(read_bounded(manifest))
    except (OSError, ValueError) as exc:
        raise AuthorityError(f"trusted Git runtime manifest is invalid: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {"schema_version", "root", "files"} or document.get("schema_version") != "1.0" or not isinstance(document.get("root"), str) or not isinstance(document.get("files"), dict):
        raise AuthorityError("trusted Git runtime manifest schema is invalid")
    root = Path(document["root"])
    try:
        metadata = root.lstat()
        if root.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise AuthorityError("trusted Git runtime root must not be a link")
        root = root.resolve(strict=True)
        resolved_relative = resolved.relative_to(root).as_posix()
    except (OSError, ValueError) as exc:
        raise AuthorityError(f"trusted Git executable is outside its runtime root: {exc}") from exc
    expected_files = document["files"]
    if not expected_files or len(expected_files) > MAX_GIT_RUNTIME_FILES:
        raise AuthorityError("trusted Git runtime manifest file count is invalid")
    actual_files: dict[str, str] = {}
    for path in root.rglob("*"):
        metadata = path.lstat()
        if path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise AuthorityError("trusted Git runtime tree contains a link or reparse point")
        if path.is_file():
            actual_files[path.relative_to(root).as_posix()] = _hash_runtime_file(path)
    if actual_files != expected_files or expected_files.get(resolved_relative) != expected_sha256:
        raise AuthorityError("trusted Git runtime tree differs from its pinned manifest")
    return resolved


def run_trusted_git(
    repo: Path,
    executable: Path | None,
    expected_sha256: str | None,
    *args: str,
    binary: bool = False,
    manifest_path: Path | None = None,
    manifest_sha256: str | None = None,
) -> Any:
    resolved = _trusted_git_executable(repo, executable, expected_sha256, manifest_path, manifest_sha256)
    environment = os.environ.copy()
    for variable in tuple(environment):
        if variable.upper().startswith("GIT_"):
            environment.pop(variable, None)
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    try:
        process = subprocess.Popen(
            [str(resolved), "--no-replace-objects", "-C", str(repo), *args],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, env=environment, start_new_session=(os.name == "posix"),
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
                raise AuthorityError("cannot assign trusted Git to a Windows job")
        stdout_data = bytearray()
        stderr_data = bytearray()
        exceeded = threading.Event()

        def drain(stream: Any, buffer: bytearray) -> None:
            while True:
                try:
                    chunk = stream.read(64 * 1024)
                except (OSError, ValueError):
                    return
                if not chunk:
                    return
                if len(buffer) + len(chunk) > MAX_AUTHORITY_OUTPUT_BYTES:
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
                process.kill()
                process.wait()
                out_thread.join(1); err_thread.join(1)
                if out_thread.is_alive() or err_thread.is_alive():
                    process.stdout.close(); process.stderr.close()
                if exceeded.is_set():
                    if job_handle: ctypes.windll.kernel32.CloseHandle(job_handle)
                    raise AuthorityError("trusted Git output exceeds the 50 MiB limit")
                if job_handle: ctypes.windll.kernel32.CloseHandle(job_handle)
                raise AuthorityError("trusted Git timed out")
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
            raise AuthorityError("trusted Git left descendant processes holding output pipes")
        if job_handle: ctypes.windll.kernel32.CloseHandle(job_handle)
        process.stdout.close(); process.stderr.close()
        if exceeded.is_set():
            raise AuthorityError("trusted Git output exceeds the 50 MiB limit")
        result_code = process.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuthorityError(f"trusted Git is unavailable: {exc}") from exc
    if result_code != 0:
        stderr = bytes(stderr_data).decode("utf-8", "replace")
        raise AuthorityError(f"git {' '.join(args)} failed: {stderr.strip()}")
    if binary:
        return bytes(stdout_data)
    try:
        return bytes(stdout_data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuthorityError("trusted Git stdout is not strict UTF-8") from exc


def _resolve_git(
    authority: Mapping[str, Any],
    repository_map: Mapping[str, Path],
    git_executable: Path | None,
    git_sha256: str | None,
    git_manifest: Path | None,
    git_manifest_sha256: str | None,
) -> bytes:
    expected = {"schema_version", "kind", "repository_uri", "commit", "path"}
    if set(authority) != expected or authority.get("schema_version") != "1.0" or authority.get("kind") != "git":
        raise AuthorityError("git authority has unknown, missing, or invalid fields")
    uri = authority.get("repository_uri")
    commit = authority.get("commit")
    if not isinstance(uri, str) or not uri:
        raise AuthorityError("git authority repository_uri is required")
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise AuthorityError("git authority commit must be a full 40- or 64-character object ID")
    repo = repository_map.get(uri)
    if repo is None:
        raise AuthorityError(f"no pinned checkout mapping for {uri}")
    repo = repo.resolve()
    if not (repo / ".git").exists():
        raise AuthorityError(f"mapped checkout is not a Git repository: {repo}")
    git_options = {"manifest_path": git_manifest, "manifest_sha256": git_manifest_sha256}
    remotes = [line.strip() for line in str(run_trusted_git(repo, git_executable, git_sha256, "remote", "get-url", "--all", "origin", **git_options)).splitlines() if line.strip()]
    if uri not in remotes:
        raise AuthorityError(f"mapped checkout origin does not match {uri}")
    resolved = str(run_trusted_git(repo, git_executable, git_sha256, "rev-parse", "--verify", f"{commit}^{{commit}}", **git_options)).strip()
    if resolved != commit:
        raise AuthorityError("authority commit does not resolve to the exact pinned object ID")
    path = _safe_git_path(authority.get("path"))
    entry = str(run_trusted_git(repo, git_executable, git_sha256, "ls-tree", commit, "--", path, **git_options)).strip()
    if not entry:
        raise AuthorityError(f"authority path is absent at pinned commit: {path}")
    mode = entry.split(None, 1)[0]
    if mode in {"120000", "160000"}:
        raise AuthorityError("symlink and submodule authority paths are not accepted")
    return bytes(run_trusted_git(repo, git_executable, git_sha256, "cat-file", "blob", f"{commit}:{path}", binary=True, **git_options))


def resolve_authority(
    authority: Mapping[str, Any],
    *,
    repository_map: Mapping[str, Path],
    delivery_root: Path | None = None,
    provider_profiles: Mapping[str, Mapping[str, Any]] | None = None,
    git_executable: Path | None = None,
    git_sha256: str | None = None,
    git_manifest: Path | None = None,
    git_manifest_sha256: str | None = None,
) -> bytes:
    kind = authority.get("kind")
    if kind == "git":
        return _resolve_git(authority, repository_map, git_executable, git_sha256, git_manifest, git_manifest_sha256)
    if kind == "provider":
        required = {
            "schema_version", "kind", "profile_id", "profile_version", "profile_digest", "native_id",
            "artifact_kind", "repository_uri", "commit", "path",
        }
        if set(authority) != required or authority.get("schema_version") != "1.0":
            raise AuthorityError("provider authority has unknown, missing, or invalid fields")
        profile_id = authority.get("profile_id")
        profiles = provider_profiles or {}
        profile = profiles.get(f"{profile_id}@{authority.get('profile_version')}")
        if profile is None or profile.get("digest") != authority.get("profile_digest"):
            raise AuthorityError("provider authority does not resolve to the pinned profile digest")
        record = profile.get("record")
        mapping = record.get("id_mapping", {}).get(authority.get("native_id")) if isinstance(record, dict) else None
        if not isinstance(mapping, dict):
            raise AuthorityError("provider native ID is absent from the pinned profile")
        if mapping.get("artifact_type") != authority.get("artifact_kind") or mapping.get("authority_uri") != authority.get("path"):
            raise AuthorityError("provider artifact kind or authority path differs from the pinned native mapping")
        if record.get("repository_uri") != authority.get("repository_uri") or record.get("commit") != authority.get("commit"):
            raise AuthorityError("provider repository pin differs from the pinned profile")
        git_authority = {
            "schema_version": "1.0",
            "kind": "git",
            "repository_uri": authority["repository_uri"],
            "commit": authority["commit"],
            "path": authority["path"],
        }
        return _resolve_git(git_authority, repository_map, git_executable, git_sha256, git_manifest, git_manifest_sha256)
    if kind == "delivery_blob":
        if set(authority) != {"schema_version", "kind", "digest"} or authority.get("schema_version") != "1.0":
            raise AuthorityError("delivery_blob authority has unknown, missing, or invalid fields")
        digest = authority.get("digest")
        if not isinstance(digest, dict):
            raise AuthorityError("delivery_blob digest is required")
        validate_digest(digest)
        if digest["canonicalization"] != "raw-v1":
            raise AuthorityError("delivery blobs use raw-v1 canonicalization")
        if delivery_root is None:
            raise AuthorityError("delivery root is required for delivery_blob authority")
        from .ledger import generation_directories, read_head

        head = read_head(delivery_root)
        paths = []
        for generation in generation_directories(delivery_root):
            sequence = int(generation.name.split("-", 1)[0])
            if sequence <= head.sequence:
                candidate = generation / "views" / "blobs" / "sha256" / digest["value"]
                if candidate.is_file():
                    paths.append(candidate)
        if len(paths) != 1:
            raise AuthorityError(f"delivery blob must resolve exactly once: {digest['value']}")
        try:
            from .canonical import read_bounded

            data = read_bounded(paths[0])
        except OSError as exc:
            raise AuthorityError(f"cannot read delivery blob {digest['value']}: {exc}") from exc
        verify_digest(data, digest)
        return data
    raise AuthorityError(f"unknown authority kind: {kind}")


def resolve_and_verify(
    authority: Mapping[str, Any],
    expected_digest: Mapping[str, Any],
    **kwargs: Any,
) -> bytes:
    if authority.get("kind") == "provider":
        profiles = kwargs.get("provider_profiles") or {}
        profile = profiles.get(f"{authority.get('profile_id')}@{authority.get('profile_version')}")
        record = profile.get("record") if isinstance(profile, Mapping) else None
        mapping = record.get("id_mapping", {}).get(authority.get("native_id")) if isinstance(record, Mapping) else None
        if not isinstance(mapping, Mapping):
            raise AuthorityError("provider native ID is absent from the pinned profile")
        if (
            mapping.get("content_hash") != expected_digest.get("value")
            or mapping.get("content_canonicalization", "raw-v1") != expected_digest.get("canonicalization")
        ):
            raise AuthorityError("provider artifact digest differs from the pinned native mapping")
    data = resolve_authority(authority, **kwargs)
    if authority.get("kind") == "provider" and isinstance(mapping, Mapping):
        selector = mapping.get("content_selector")
        if selector is not None:
            if not isinstance(selector, Mapping):
                raise AuthorityError("provider content selector must be an object")
            data = _select_provider_content(data, selector)
    verify_digest(data, expected_digest)
    return data
