#!/usr/bin/env python3
"""Dependency-free JSON helpers shared by delivery gate scripts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from typing import Any


class InputError(Exception):
    """Input JSON or schema is malformed."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON in {path}: {exc}") from exc


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def validate_schema(value: Any, schema: dict[str, Any], root: dict[str, Any] | None = None, where: str = "$") -> list[str]:
    root = root or schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            return [f"{where}: unsupported schema reference {ref}"]
        target: Any = root
        for part in ref[2:].split("/"):
            target = target.get(part.replace("~1", "/").replace("~0", "~")) if isinstance(target, dict) else None
        return [f"{where}: unresolved schema reference {ref}"] if not isinstance(target, dict) else validate_schema(value, target, root, where)

    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, item) for item in types):
            return [f"{where}: expected {' or '.join(types)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: value {value!r} is not in enum")

    if isinstance(value, dict):
        required = schema.get("required", [])
        errors.extend(f"{where}: missing required property {key}" for key in required if key not in value)
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            child = f"{where}.{key}"
            if key in properties:
                errors.extend(validate_schema(item, properties[key], root, child))
            elif additional is False:
                errors.append(f"{child}: additional property is not allowed")
            elif isinstance(additional, dict):
                errors.extend(validate_schema(item, additional, root, child))
        if len(value) < schema.get("minProperties", 0):
            errors.append(f"{where}: requires at least {schema['minProperties']} properties")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{where}: requires at least {schema['minItems']} items")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(validate_schema(item, schema["items"], root, f"{where}[{index}]"))
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{where}: string is shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{where}: string does not match required pattern")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    errors.append(f"{where}: date-time must include a timezone")
            except ValueError:
                errors.append(f"{where}: invalid date-time")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", value):
            errors.append(f"{where}: value is below minimum {schema['minimum']}")
    return errors


def validate_file(data_path: Path, schema_path: Path) -> tuple[Any, list[str]]:
    data = load_json(data_path)
    schema = load_json(schema_path)
    if not isinstance(schema, dict):
        raise InputError(f"schema is not an object: {schema_path}")
    return data, validate_schema(data, schema)


def artifact_index(registry: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Index governed artifacts by their stable identity."""
    return {(item["artifact_id"], item["version"]): item for item in registry["artifacts"]}


def approval_match_errors(
    approval: dict[str, Any] | None,
    *,
    approval_id: str,
    object_id: str,
    object_version: str,
    content_hash: str,
    decisions: set[str],
    required_scope: set[str] | None = None,
) -> list[str]:
    """Validate that an approval is current and bound to one governed artifact version."""
    if approval is None:
        return [f"approval does not exist: {approval_id}"]
    errors: list[str] = []
    expected = {
        "approval_id": approval_id,
        "object_id": object_id,
        "object_version": object_version,
        "content_hash": content_hash,
    }
    for field, value in expected.items():
        if approval.get(field) != value:
            errors.append(f"approval {approval_id} {field} does not match governed object")
    if approval.get("decision") not in decisions:
        errors.append(f"approval {approval_id} decision is not one of {sorted(decisions)}")
    expires_at = approval.get("expires_at")
    if expires_at:
        try:
            expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
                errors.append(f"approval {approval_id} is expired or lacks timezone")
        except ValueError:
            errors.append(f"approval {approval_id} expires_at is invalid")
    if required_scope is not None:
        approved_scope = approval.get("scope")
        if not isinstance(approved_scope, list) or not required_scope.issubset(set(approved_scope)):
            errors.append(f"approval {approval_id} does not cover the required scope")
    return errors


def emit(ok: bool, errors: list[str], payload: dict[str, Any], as_json: bool) -> None:
    result = {"ok": ok, "errors": errors, **payload}
    if as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        for error in errors:
            print("ERROR: " + error, file=sys.stderr)
    elif ok:
        print("PASS: " + payload.get("summary", "gate passed"))
    else:
        for error in errors:
            print("ERROR: " + error, file=sys.stderr)


NORMAL_TRANSITIONS = {
    "greenfield": [("captured", "baselined"), ("baselined", "planned"), ("planned", "executing"), ("executing", "verified"), ("verified", "closed")],
    "brownfield": [("captured", "baselined"), ("baselined", "planned"), ("planned", "executing"), ("executing", "implementation_accepted"), ("implementation_accepted", "release_ready"), ("release_ready", "releasing"), ("releasing", "released"), ("released", "production_validated"), ("production_validated", "closed")],
    "task": [("draft", "approved"), ("approved", "implementing"), ("implementing", "verifying"), ("verifying", "accepted")],
    "contract": [("draft", "reviewed"), ("reviewed", "frozen"), ("frozen", "superseded"), ("frozen", "retired")],
}
EXCEPTIONAL = {"blocked", "failed", "stale", "deprecated"}


def transition_allowed(kind: str, old: str, new: str, recovery_origin: str | None = None) -> bool:
    if (old, new) in NORMAL_TRANSITIONS.get(kind, []):
        return True
    if new in EXCEPTIONAL:
        return True
    if old not in EXCEPTIONAL or recovery_origin is None:
        return False
    allowed_recovery = {recovery_origin}
    allowed_recovery.update(target for source, target in NORMAL_TRANSITIONS.get(kind, []) if source == recovery_origin)
    return new in allowed_recovery
