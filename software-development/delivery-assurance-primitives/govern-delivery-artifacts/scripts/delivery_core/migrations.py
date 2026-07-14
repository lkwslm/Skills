"""Deterministic, one-shot import of legacy sidecar data without granting authority."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from .authority import digest_bytes
from .canonical import canonical_json_bytes, loads_strict, read_bounded


class MigrationError(ValueError):
    """Legacy data cannot be inventoried without ambiguity or loss."""


MAX_LEGACY_BYTES = 50 * 1024 * 1024


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _record_ids(relative: str, data: bytes) -> list[str]:
    if not relative.endswith(".json"):
        return []
    try:
        value = loads_strict(data)
    except ValueError:
        return []
    found: list[str] = []
    id_fields = {"approval_id", "artifact_id", "audit_id", "evidence_id", "run_id", "object_id", "package_id"}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in id_fields and isinstance(child, str) and child:
                    found.append(child)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def archive_legacy(source: Path, source_format: str) -> tuple[bytes, list[str]]:
    if source_format not in {"legacy-specflow", "unversioned-delivery"}:
        raise MigrationError(f"unknown legacy source format: {source_format}")
    if _is_link_or_reparse(source):
        raise MigrationError(f"legacy source must not be a symlink or reparse point: {source}")
    source = source.resolve()
    if not source.is_dir():
        raise MigrationError(f"legacy source is not a directory: {source}")
    files = []
    untrusted_ids: set[str] = set()
    total = 0
    for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
        if _is_link_or_reparse(path):
            raise MigrationError(f"legacy sidecar contains a symlink: {path.relative_to(source)}")
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
        try:
            data = read_bounded(path, limit=MAX_LEGACY_BYTES - total)
        except ValueError as exc:
            raise MigrationError(str(exc)) from exc
        total += len(data)
        if total > MAX_LEGACY_BYTES:
            raise MigrationError("legacy sidecar exceeds the 50 MiB explicit migration limit")
        digest = digest_bytes(data, "raw-v1")
        files.append({
            "path": relative,
            "digest": digest,
            "content_base64": base64.b64encode(data).decode("ascii"),
        })
        try:
            untrusted_ids.update(_record_ids(relative, data))
        except RecursionError as exc:
            raise MigrationError(f"legacy record nesting is too deep: {relative}") from exc
    if not files:
        raise MigrationError("legacy sidecar contains no files")
    archive = {
        "schema_version": "1.0",
        "source_format": source_format,
        "files": files,
    }
    return canonical_json_bytes(archive), sorted(untrusted_ids)


def build_import_operation(
    archive: bytes,
    untrusted_ids: list[str],
    *,
    source_format: str,
    migration_id: str,
    operation_id: str,
    imported_at: str,
) -> tuple[dict[str, Any], str]:
    blob_digest = digest_bytes(archive, "raw-v1")
    source_value = loads_strict(archive)
    source_digest = digest_bytes(canonical_json_bytes(source_value), "delivery-json-v1")
    operation = {
        "schema_version": "1.0",
        "operation_id": operation_id,
        "type": "legacy_imported",
        "payload": {
            "migration": {
                "schema_version": "1.0",
                "migration_id": migration_id,
                "source_format": source_format,
                "source_digest": source_digest,
                "blob_digest": blob_digest,
                "untrusted_record_ids": untrusted_ids,
                "imported_at": imported_at,
            }
        },
    }
    return operation, blob_digest["value"]
