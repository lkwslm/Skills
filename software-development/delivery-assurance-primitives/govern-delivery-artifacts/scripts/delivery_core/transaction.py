"""CAS transaction storage with atomic generation visibility."""

from __future__ import annotations

import errno
import os
import stat
import shutil
import re
from pathlib import Path, PurePosixPath
import uuid
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .canonical import canonical_json_bytes, loads_strict, read_bounded, sha256_hex
from .ledger import (
    GENERATION_PATTERN,
    HASH_PATTERN,
    KeyResolver,
    LedgerError,
    Revision,
    generation_directories,
    generation_name,
    head_document,
    load_committed_events,
    read_head,
    read_head_document,
    validate_chain,
    verify_event,
)


class TransactionError(RuntimeError):
    """A durable transaction could not be completed."""


class LockUnavailable(TransactionError):
    """Another writer owns the repository-local lock."""


class RevisionConflict(TransactionError):
    """The caller's externally anchored expected HEAD is stale."""


class RecoveryRequired(TransactionError):
    """Uncommitted durable state must be recovered before another write."""


class SimulatedCrash(TransactionError):
    """Test-only fault used to prove transaction recovery semantics."""


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def ensure_store_confinement(delivery_dir: Path) -> None:
    """Reject symlinks/reparse points anywhere in the mutable ledger control tree."""
    delivery = Path(delivery_dir)
    if not delivery.exists():
        return
    if _is_link_or_reparse(delivery) or not delivery.is_dir():
        raise TransactionError("delivery store must be a real directory, not a link or reparse point")

    def scan(directory: Path) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise TransactionError(f"cannot inspect delivery store confinement: {directory}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink() or _is_link_or_reparse(path):
                raise TransactionError(f"delivery store contains a link or reparse point: {path}")
            if entry.is_dir(follow_symlinks=False):
                scan(path)

    scan(delivery)


class RepositoryLock:
    """Non-blocking OS lock whose ownership is released by process death."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle = None

    def __enter__(self) -> "RepositoryLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        self._handle.seek(0, os.SEEK_END)
        if self._handle.tell() == 0:
            self._handle.write(b"\0")
            self._handle.flush()
            os.fsync(self._handle.fileno())
        self._handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            elif os.name == "posix":
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:  # pragma: no cover - supported platforms are Windows and POSIX
                raise TransactionError("no supported repository lock for " + os.name)
        except (OSError, IOError) as exc:
            self._handle.close()
            self._handle = None
            if getattr(exc, "errno", None) in {
                errno.EACCES,
                errno.EAGAIN,
                errno.EDEADLK,
            } or os.name == "nt":
                raise LockUnavailable("delivery repository lock is already held") from exc
            raise TransactionError("cannot acquire delivery repository lock") from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        handle = kernel.CreateFileW(str(path), 0x80000000 | 0x40000000, 0x00000007, None, 3, 0x02000000 | 0x80000000, None)
        invalid = wintypes.HANDLE(-1).value
        if handle == invalid:
            raise TransactionError(f"cannot open directory for durable flush: {path}: {ctypes.get_last_error()}")
        try:
            if not kernel.FlushFileBuffers(handle):
                raise TransactionError(f"cannot flush directory metadata: {path}: {ctypes.get_last_error()}")
        finally:
            kernel.CloseHandle(handle)
        return
    if os.name != "posix":
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_durable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _safe_view_path(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name or "\\" in name:
        raise TransactionError("view path must be a non-empty POSIX relative path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TransactionError("view path escapes the generation: " + name)
    return path


def _manifest_files(
    generation: Path, *, enforce_generation_name: bool = True
) -> Dict[str, Any]:
    manifest_path = generation / "manifest.json"
    try:
        manifest = loads_strict(read_bounded(manifest_path))
    except (OSError, ValueError) as exc:
        raise RecoveryRequired("prepared generation has no readable manifest") from exc
    required = {"schema_version", "generation", "parent_revision", "files"}
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise RecoveryRequired("prepared generation manifest is invalid")
    if manifest.get("schema_version") != "1.0":
        raise RecoveryRequired("prepared generation manifest identity is invalid")
    if enforce_generation_name and manifest.get("generation") != generation.name:
        raise RecoveryRequired("prepared generation manifest identity is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RecoveryRequired("prepared generation manifest has no files")
    for relative, expected_hash in files.items():
        safe = _safe_view_path(relative)
        target = generation.joinpath(*safe.parts)
        if not target.is_file() or not isinstance(expected_hash, str) or not HASH_PATTERN.fullmatch(expected_hash):
            raise RecoveryRequired("prepared generation file is missing or invalid: " + relative)
        try:
            actual_hash = sha256_hex(read_bounded(target))
        except (OSError, ValueError) as exc:
            raise RecoveryRequired("prepared generation file cannot be read: " + relative) from exc
        if actual_hash != expected_hash:
            raise RecoveryRequired("prepared generation file hash mismatch: " + relative)
    actual_files = {
        path.relative_to(generation).as_posix()
        for path in generation.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_files != set(files):
        raise RecoveryRequired("prepared generation contains unmanifested files")
    return manifest


def _verify_generation(
    generation: Path,
    parent: Revision,
    key_resolver: KeyResolver,
    *,
    enforce_directory_name: bool = True,
) -> Tuple[Revision, str]:
    manifest = _manifest_files(generation, enforce_generation_name=enforce_directory_name)
    if manifest.get("parent_revision") != str(parent):
        raise RecoveryRequired("prepared generation parent revision is stale")
    try:
        event = loads_strict(read_bounded(generation / "event.json"))
        public_key = key_resolver(event)
        revision = verify_event(
            event,
            public_key,
            expected_sequence=parent.sequence + 1,
            expected_previous_hash=parent.event_hash,
        )
    except Exception as exc:
        raise RecoveryRequired("prepared event cannot be trusted: " + str(exc)) from exc
    expected_name = generation_name(revision)
    if manifest.get("generation") != expected_name or (enforce_directory_name and generation.name != expected_name):
        raise RecoveryRequired("prepared generation identity does not match its signed event")
    manifest_hash = sha256_hex(canonical_json_bytes(manifest))
    return revision, manifest_hash


def _pending_entries(delivery_dir: Path, head: Revision) -> Tuple[list, list, list]:
    transactions = Path(delivery_dir) / ".transactions"
    stages = [] if not transactions.exists() else [path for path in transactions.iterdir() if path.name.endswith(".prepared")]
    invalid = [] if not transactions.exists() else [
        path for path in transactions.iterdir()
        if not path.name.endswith(".prepared") and not path.name.endswith(".building")
    ]
    if invalid:
        raise RecoveryRequired("transaction staging contains invalid entries")
    temporary_heads = list(Path(delivery_dir).glob(".HEAD.*.tmp"))
    generations = generation_directories(delivery_dir)
    orphans = [
        path
        for path in generations
        if int(GENERATION_PATTERN.fullmatch(path.name).group(1)) > head.sequence
    ]
    return stages, temporary_heads, orphans


def _cleanup_incomplete_builds(delivery_dir: Path) -> None:
    transactions = Path(delivery_dir) / ".transactions"
    if not transactions.exists():
        return
    for path in transactions.iterdir():
        if path.name.endswith(".building"):
            raise RecoveryRequired(
                "incomplete transaction build is present; use the explicit deliveryctl discard-building operation"
            )


def inspect_store(
    delivery_dir: Path,
    *,
    expected_revision: Revision,
    key_resolver: KeyResolver,
) -> Revision:
    """Verify committed storage against an external expected HEAD."""
    delivery = Path(delivery_dir)
    ensure_store_confinement(delivery)
    current = read_head(delivery)
    if current != expected_revision:
        raise RevisionConflict(
            "current HEAD {} does not match expected revision {}".format(
                current, expected_revision
            )
        )
    stages, temporary_heads, orphans = _pending_entries(delivery, current)
    if stages or temporary_heads or orphans:
        raise RecoveryRequired("uncommitted delivery transaction requires recovery")
    events = load_committed_events(delivery, current)
    validate_chain(events, key_resolver, expected_head=expected_revision)
    committed_generations = [
        path
        for path in generation_directories(delivery)
        if int(GENERATION_PATTERN.fullmatch(path.name).group(1)) <= current.sequence
    ]
    for generation in committed_generations:
        _manifest_files(generation)
    if current.sequence:
        document = read_head_document(delivery)
        generation = delivery / "generations" / document["generation"]
        manifest = _manifest_files(generation)
        if sha256_hex(canonical_json_bytes(manifest)) != document["manifest_hash"]:
            raise LedgerError("HEAD manifest_hash does not match committed generation")
    return current


def commit_event(
    delivery_dir: Path,
    *,
    expected_revision: Revision,
    event: Mapping[str, Any],
    key_resolver: KeyResolver,
    views: Optional[Mapping[str, Any]] = None,
    fault_injector: Optional[Callable[[str], None]] = None,
) -> Revision:
    """Durably commit one event and derived views using a HEAD CAS."""
    delivery = Path(delivery_dir)
    ensure_store_confinement(delivery)
    delivery.mkdir(parents=True, exist_ok=True)
    (delivery / "generations").mkdir(exist_ok=True)
    (delivery / ".transactions").mkdir(exist_ok=True)
    ensure_store_confinement(delivery)
    with RepositoryLock(delivery / ".lock"):
        _cleanup_incomplete_builds(delivery)
        current = inspect_store(
            delivery, expected_revision=expected_revision, key_resolver=key_resolver
        )
        try:
            public_key = key_resolver(event)
            revision = verify_event(
                event,
                public_key,
                expected_sequence=current.sequence + 1,
                expected_previous_hash=current.event_hash,
            )
        except Exception as exc:
            raise TransactionError("new event cannot be trusted: " + str(exc)) from exc
        encoded_views: Dict[str, bytes] = {}
        for name, value in (views or {}).items():
            path = _safe_view_path(name)
            relative = "views/" + path.as_posix()
            encoded_views[relative] = (
                bytes(value) if isinstance(value, (bytes, bytearray))
                else canonical_json_bytes(value)
            )
        transaction_id = uuid.uuid4().hex
        stage = delivery / ".transactions" / (transaction_id + ".building")
        stage.mkdir()
        if fault_injector:
            fault_injector("after_stage_mkdir")
        event_bytes = canonical_json_bytes(event)
        _write_durable(stage / "event.json", event_bytes)
        if fault_injector:
            fault_injector("after_event_write")
        file_hashes = {"event.json": sha256_hex(event_bytes)}
        for relative, content in sorted(encoded_views.items()):
            _write_durable(stage.joinpath(*PurePosixPath(relative).parts), content)
            file_hashes[relative] = sha256_hex(content)
        if fault_injector:
            fault_injector("after_views_write")
        manifest = {
            "schema_version": "1.0",
            "generation": generation_name(revision),
            "parent_revision": str(current),
            "files": file_hashes,
        }
        manifest_bytes = canonical_json_bytes(manifest)
        _write_durable(stage / "manifest.json", manifest_bytes)
        _fsync_directory(stage)
        prepared = delivery / ".transactions" / (transaction_id + ".prepared")
        os.replace(str(stage), str(prepared))
        _fsync_directory(prepared.parent)
        if fault_injector:
            fault_injector("after_stage_fsync")
        generation = delivery / "generations" / generation_name(revision)
        os.replace(str(prepared), str(generation))
        _fsync_directory(generation.parent)
        if fault_injector:
            fault_injector("after_generation_install")
        head = head_document(revision, sha256_hex(manifest_bytes))
        head_temp = delivery / (".HEAD." + transaction_id + ".tmp")
        _write_durable(head_temp, canonical_json_bytes(head))
        os.replace(str(head_temp), str(delivery / "HEAD.json"))
        _fsync_directory(delivery)
        if fault_injector:
            fault_injector("after_head_replace")
        return revision


def recover_transaction(
    delivery_dir: Path,
    *,
    expected_revision: Revision,
    key_resolver: KeyResolver,
) -> Revision:
    """Roll one fully durable prepared transaction forward; never roll back."""
    delivery = Path(delivery_dir)
    ensure_store_confinement(delivery)
    with RepositoryLock(delivery / ".lock"):
        _cleanup_incomplete_builds(delivery)
        current = read_head(delivery)
        if current != expected_revision:
            raise RevisionConflict(
                "current HEAD {} does not match expected revision {}".format(
                    current, expected_revision
                )
            )
        events = load_committed_events(delivery, current)
        validate_chain(events, key_resolver, expected_head=current)
        stages, temporary_heads, orphans = _pending_entries(delivery, current)
        directory_stages = [path for path in stages if path.is_dir()]
        file_stages = [path for path in stages if not path.is_dir()]
        if file_stages:
            raise RecoveryRequired("transaction staging contains invalid entries")
        if len(directory_stages) + len(orphans) != 1:
            raise RecoveryRequired("recovery requires exactly one prepared generation")
        if directory_stages:
            prepared = directory_stages[0]
            revision, manifest_hash = _verify_generation(
                prepared, current, key_resolver, enforce_directory_name=False
            )
            target_name = generation_name(revision)
            if not isinstance(target_name, str) or GENERATION_PATTERN.fullmatch(target_name) is None:
                raise RecoveryRequired("prepared transaction generation name is invalid")
            target = delivery / "generations" / target_name
            if target.exists():
                raise RecoveryRequired("prepared transaction target already exists")
            os.replace(str(prepared), str(target))
            _fsync_directory(target.parent)
            prepared = target
        else:
            prepared = orphans[0]
            revision, manifest_hash = _verify_generation(prepared, current, key_resolver)
        head = head_document(revision, manifest_hash)
        transaction_id = uuid.uuid4().hex
        head_temp = delivery / (".HEAD." + transaction_id + ".tmp")
        _write_durable(head_temp, canonical_json_bytes(head))
        os.replace(str(head_temp), str(delivery / "HEAD.json"))
        _fsync_directory(delivery)
        for path in temporary_heads:
            try:
                path.unlink()
            except (OSError, ValueError) as exc:
                raise RecoveryRequired("cannot remove obsolete HEAD candidate") from exc
        return revision


def discard_incomplete_builds(
    delivery_dir: Path,
    *,
    expected_revision: Revision,
    key_resolver: KeyResolver,
) -> Revision:
    """Explicitly discard only pre-prepared crash residue under the repository lock."""
    delivery = Path(delivery_dir)
    ensure_store_confinement(delivery)
    with RepositoryLock(delivery / ".lock"):
        current = read_head(delivery)
        if current != expected_revision:
            raise RevisionConflict("current HEAD does not match expected revision")
        events = load_committed_events(delivery, current)
        validate_chain(events, key_resolver, expected_head=current)
        stages, temporary_heads, orphans = _pending_entries(delivery, current)
        if stages or temporary_heads or orphans:
            raise RecoveryRequired("prepared transaction exists; recover it before discarding building residue")
        transactions = delivery / ".transactions"
        if not transactions.is_dir():
            raise RecoveryRequired("transaction staging directory is absent")
        builds = [path for path in transactions.iterdir() if path.name.endswith(".building")]
        if len(builds) != 1:
            raise RecoveryRequired("discard requires exactly one incomplete building transaction")
        for path in builds:
            if not re.fullmatch(r"[0-9a-f]{32}\.building", path.name) or not path.is_dir() or _is_link_or_reparse(path):
                raise RecoveryRequired("incomplete building transaction is invalid")
            ensure_store_confinement(path)
        for path in builds:
            shutil.rmtree(path)
        _fsync_directory(transactions)
        return current
