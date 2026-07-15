"""Strict operation schemas and capability mapping for the delivery ledger."""

from __future__ import annotations

from typing import Any, Mapping

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # required dependency; there is deliberately no permissive validator
    raise RuntimeError("jsonschema is required; install scripts/requirements.txt") from exc


SCHEMA_VERSION = "1.0"
RESULTS = ["PASS", "FAIL", "BLOCKED"]
DECISIONS = ["APPROVED", "REJECTED"]
CAPABILITIES = [
    "trust.manage", "artifact.write", "approval.write", "state.write", "run.write",
    "evidence.write", "audit.write", "claim.write", "trace.write", "provider.write",
    "migration.write", "recovery.write",
]


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


NONEMPTY = {"type": "string", "minLength": 1}
UTC_TIME = {"type": "string", "format": "date-time", "pattern": "Z$"}
DIGEST = _object({
    "algorithm": {"const": "sha256"},
    "canonicalization": {"enum": ["raw-v1", "utf8-nfc-lf-v1", "delivery-json-v1"]},
    "value": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
})
IDENTITY = _object({"artifact_id": NONEMPTY, "version": NONEMPTY, "digest": DIGEST})
GATE_REF = _object({
    "ref_type": {"enum": ["approval", "evidence", "audit"]},
    "event_id": NONEMPTY,
    "record_id": NONEMPTY,
    "record_version": NONEMPTY,
    "digest": DIGEST,
})
GIT_AUTHORITY = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "kind": {"const": "git"},
    "repository_uri": NONEMPTY,
    "commit": {"type": "string", "pattern": "^[0-9a-f]{40}([0-9a-f]{24})?$"},
    "path": NONEMPTY,
})
PROVIDER_AUTHORITY = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "kind": {"const": "provider"},
    "profile_id": NONEMPTY,
    "profile_version": NONEMPTY,
    "profile_digest": DIGEST,
    "native_id": NONEMPTY,
    "artifact_kind": NONEMPTY,
    "repository_uri": NONEMPTY,
    "commit": {"type": "string", "pattern": "^[0-9a-f]{40}([0-9a-f]{24})?$"},
    "path": NONEMPTY,
})
BLOB_AUTHORITY = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "kind": {"const": "delivery_blob"},
    "digest": DIGEST,
})
AUTHORITY = {"oneOf": [GIT_AUTHORITY, PROVIDER_AUTHORITY, BLOB_AUTHORITY]}
ARTIFACT = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "artifact_id": NONEMPTY,
    "artifact_type": {"enum": [
        "source", "requirement", "contract", "spec", "task", "implementation",
        "test", "evidence", "audit", "context-package", "spec-tool-profile", "migration",
    ]},
    "version": NONEMPTY,
    "digest": DIGEST,
    "authority": AUTHORITY,
    "derived_from": {"type": "array", "items": IDENTITY, "uniqueItems": True},
    "status": {"enum": ["active", "stale", "deprecated", "superseded"]},
    "created_at": UTC_TIME,
})
TRUST_ACTOR = _object({
    "actor_id": NONEMPTY,
    "public_key_pem": {"type": "string", "pattern": "^-----BEGIN PUBLIC KEY-----"},
    "key_fingerprint": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "roles": {"type": "array", "items": NONEMPTY, "minItems": 1, "uniqueItems": True},
    "capabilities": {"type": "array", "items": {"enum": CAPABILITIES}, "minItems": 1, "uniqueItems": True},
    "path_scopes": {"type": "array", "items": NONEMPTY, "uniqueItems": True},
    "environments": {"type": "array", "items": NONEMPTY, "uniqueItems": True},
    "valid_from": UTC_TIME,
    "valid_until": {"oneOf": [UTC_TIME, {"type": "null"}]},
    "revoked_at_sequence": {"oneOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]},
})
TRUST_POLICY = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "policy_id": NONEMPTY,
    "policy_version": NONEMPTY,
    "ledger_id": NONEMPTY,
    "root_key_fingerprint": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "actors": {"type": "array", "items": TRUST_ACTOR, "minItems": 1},
})
APPROVAL = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "approval_id": NONEMPTY,
    "version": NONEMPTY,
    "subject": IDENTITY,
    "run_id": NONEMPTY,
    "attempt_id": NONEMPTY,
    "base_commit": {"type": "string", "pattern": "^[0-9a-f]{40}([0-9a-f]{24})?$"},
    "target_commit": {"type": "string", "pattern": "^[0-9a-f]{40}([0-9a-f]{24})?$"},
    "scope": {"type": "array", "items": NONEMPTY, "minItems": 1, "uniqueItems": True},
    "environment": NONEMPTY,
    "decision": {"enum": DECISIONS},
    "issued_at": UTC_TIME,
    "expires_at": UTC_TIME,
    "nonce": NONEMPTY,
})
RUN = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "run_id": NONEMPTY,
    "suite": {"enum": ["greenfield", "brownfield"]},
    "target_commit": {"type": "string", "pattern": "^[0-9a-f]{40}([0-9a-f]{24})?$"},
    "inputs": {"type": "array", "items": IDENTITY, "minItems": 1, "uniqueItems": True},
    "started_at": UTC_TIME,
})
ATTEMPT = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "attempt_id": NONEMPTY,
    "run_id": NONEMPTY,
    "sequence": {"type": "integer", "minimum": 1},
    "target_commit": {"type": "string", "pattern": "^[0-9a-f]{40}([0-9a-f]{24})?$"},
    "input_digests": {"type": "array", "items": DIGEST, "minItems": 1, "uniqueItems": True},
    "started_at": UTC_TIME,
})
ATTEMPT_COMPLETION = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "attempt_id": NONEMPTY,
    "run_id": NONEMPTY,
    "result": {"enum": RESULTS},
    "ended_at": UTC_TIME,
    "log_digest": DIGEST,
})
EVIDENCE = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "evidence_id": NONEMPTY,
    "version": NONEMPTY,
    "subject": IDENTITY,
    "run_id": NONEMPTY,
    "attempt_id": NONEMPTY,
    "target_commit": {"type": "string", "pattern": "^[0-9a-f]{40}([0-9a-f]{24})?$"},
    "scope": {"type": "array", "items": NONEMPTY, "minItems": 1, "uniqueItems": True},
    "environment": NONEMPTY,
    "result": {"enum": RESULTS},
    "log_authority": BLOB_AUTHORITY,
    "recorded_at": UTC_TIME,
})
AUDIT_CLAUSE = _object({
    "clause_id": NONEMPTY,
    "result": {"enum": RESULTS},
    "evidence_refs": {"type": "array", "items": GATE_REF, "minItems": 1, "uniqueItems": True},
})
AUDIT = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "audit_id": NONEMPTY,
    "version": NONEMPTY,
    "subject": IDENTITY,
    "run_id": NONEMPTY,
    "attempt_id": NONEMPTY,
    "target_commit": {"type": "string", "pattern": "^[0-9a-f]{40}([0-9a-f]{24})?$"},
    "scope": {"type": "array", "items": NONEMPTY, "minItems": 1, "uniqueItems": True},
    "environment": NONEMPTY,
    "policy_version": NONEMPTY,
    "input_digests": {"type": "array", "items": DIGEST, "minItems": 1, "uniqueItems": True},
    "clauses": {"type": "array", "items": AUDIT_CLAUSE, "minItems": 1},
    "overall": {"enum": RESULTS},
    "recorded_at": UTC_TIME,
})
CLAIM = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "claim_id": NONEMPTY,
    "task": IDENTITY,
    "holder_actor_id": NONEMPTY,
    "lease_token": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "fencing_token": {"type": "integer", "minimum": 1},
    "acquired_at": UTC_TIME,
    "expires_at": UTC_TIME,
})
STATE_OBJECT = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "object": IDENTITY,
    "kind": {"enum": ["greenfield", "brownfield", "task", "contract"]},
    "initial_state": {"enum": ["captured", "draft"]},
})
TRANSITION = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "transition_id": NONEMPTY,
    "object": IDENTITY,
    "old_state": NONEMPTY,
    "new_state": NONEMPTY,
    "run_id": NONEMPTY,
    "attempt_id": NONEMPTY,
    "target_commit": {"type": "string", "pattern": "^[0-9a-f]{40}([0-9a-f]{24})?$"},
    "scope": {"type": "array", "items": NONEMPTY, "minItems": 1, "uniqueItems": True},
    "environment": NONEMPTY,
    "gate_refs": {"type": "array", "items": GATE_REF, "minItems": 1, "uniqueItems": True},
})
TRACE_NODE = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "node": IDENTITY,
    "node_type": {"enum": [
        "source", "requirement", "contract", "spec", "task", "implementation",
        "test", "evidence", "audit", "context-package", "risk-acceptance", "migration-plan",
        "observation-plan", "stop-condition", "current-behavior", "target-behavior",
        "unchanged-behavior",
    ]},
})
TRACE_EDGE = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "edge_id": NONEMPTY,
    "from": IDENTITY,
    "to": IDENTITY,
    "relation": {"enum": [
        "derives", "specifies", "implements", "verifies", "audits", "mitigates",
        "migrates", "observes", "stops", "preserves",
    ]},
})
PROVIDER_PROFILE = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "profile_id": NONEMPTY,
    "version": NONEMPTY,
    "provider": {"enum": ["openspec", "spec-kit"]},
    "mode": {"const": "native"},
    "provider_version": NONEMPTY,
    "repository_uri": NONEMPTY,
    "commit": {"type": "string", "pattern": "^[0-9a-f]{40}([0-9a-f]{24})?$"},
    "id_mapping": {
        "type": "object",
        "additionalProperties": _object({
            "delivery_id": NONEMPTY,
            "native_id": NONEMPTY,
            "native_parent_id": {"oneOf": [NONEMPTY, {"type": "null"}]},
            "artifact_type": NONEMPTY,
            "authority_uri": NONEMPTY,
            "status": NONEMPTY,
            "content_hash": {"oneOf": [{"type": "string", "pattern": "^[0-9a-f]{64}$"}, {"type": "null"}]},
            "content_canonicalization": {"enum": ["raw-v1", "utf8-nfc-lf-v1", "delivery-json-v1"]},
            "content_selector": _object({"kind": {"const": "openspec-task-v1"}, "task_id": NONEMPTY}),
        }, required=[
            "delivery_id", "native_id", "native_parent_id", "artifact_type",
            "authority_uri", "status", "content_hash",
        ]),
    },
    "observation_authority": BLOB_AUTHORITY,
    "observed_at": UTC_TIME,
})
LEGACY_IMPORT = _object({
    "schema_version": {"const": SCHEMA_VERSION},
    "migration_id": NONEMPTY,
    "source_format": {"enum": ["legacy-specflow", "unversioned-delivery"]},
    "source_digest": DIGEST,
    "blob_digest": DIGEST,
    "untrusted_record_ids": {"type": "array", "items": NONEMPTY, "uniqueItems": True},
    "imported_at": UTC_TIME,
})


PAYLOAD_SCHEMAS: dict[str, dict[str, Any]] = {
    "trust_policy_initialized": _object({"policy": TRUST_POLICY}),
    "trust_policy_rotated": _object({"policy": TRUST_POLICY}),
    "artifact_registered": _object({"artifact": ARTIFACT}),
    "artifact_superseded": _object({"artifact_id": NONEMPTY, "previous_version": NONEMPTY, "artifact": ARTIFACT}),
    "approval_recorded": _object({"approval": APPROVAL}),
    "run_started": _object({"run": RUN}),
    "attempt_started": _object({"attempt": ATTEMPT}),
    "attempt_completed": _object({"completion": ATTEMPT_COMPLETION}),
    "evidence_recorded": _object({"evidence": EVIDENCE}),
    "audit_recorded": _object({"audit": AUDIT}),
    "claim_acquired": _object({"claim": CLAIM}),
    "claim_renewed": _object({"claim_id": NONEMPTY, "lease_token": NONEMPTY, "fencing_token": {"type": "integer", "minimum": 1}, "expires_at": UTC_TIME}),
    "claim_expired": _object({"claim_id": NONEMPTY, "lease_token": NONEMPTY, "fencing_token": {"type": "integer", "minimum": 1}, "expired_at": UTC_TIME}),
    "claim_released": _object({"claim_id": NONEMPTY, "lease_token": NONEMPTY, "fencing_token": {"type": "integer", "minimum": 1}, "released_at": UTC_TIME}),
    "state_object_registered": _object({"state_object": STATE_OBJECT}),
    "state_transitioned": _object({"transition": TRANSITION, "claim_id": NONEMPTY, "lease_token": NONEMPTY, "fencing_token": {"type": "integer", "minimum": 1}}),
    "trace_node_recorded": _object({"node": TRACE_NODE}),
    "trace_edge_recorded": _object({"edge": TRACE_EDGE}),
    "provider_profile_observed": _object({"profile": PROVIDER_PROFILE}),
    "legacy_imported": _object({"migration": LEGACY_IMPORT}),
}

EVENT_CAPABILITY = {
    "trust_policy_initialized": "trust.manage", "trust_policy_rotated": "trust.manage",
    "artifact_registered": "artifact.write", "artifact_superseded": "artifact.write",
    "approval_recorded": "approval.write", "run_started": "run.write",
    "attempt_started": "run.write", "attempt_completed": "run.write",
    "evidence_recorded": "evidence.write", "audit_recorded": "audit.write",
    "claim_acquired": "claim.write", "claim_renewed": "claim.write",
    "claim_expired": "claim.write", "claim_released": "claim.write",
    "state_object_registered": "state.write", "state_transitioned": "state.write",
    "trace_node_recorded": "trace.write", "trace_edge_recorded": "trace.write",
    "provider_profile_observed": "provider.write", "legacy_imported": "migration.write",
}


class OperationError(ValueError):
    """Operation is unknown or violates its strict schema."""


def validate_operation(operation: Mapping[str, Any]) -> None:
    outer = _object({
        "schema_version": {"const": SCHEMA_VERSION},
        "operation_id": NONEMPTY,
        "type": {"enum": sorted(PAYLOAD_SCHEMAS)},
        "payload": {"type": "object"},
    })
    errors = list(Draft202012Validator(outer, format_checker=Draft202012Validator.FORMAT_CHECKER).iter_errors(operation))
    event_type = operation.get("type")
    payload_schema = PAYLOAD_SCHEMAS.get(str(event_type))
    if payload_schema is not None:
        errors.extend(Draft202012Validator(payload_schema, format_checker=Draft202012Validator.FORMAT_CHECKER).iter_errors(operation.get("payload")))
    if errors:
        details = "; ".join(error.message for error in sorted(errors, key=lambda item: tuple(str(part) for part in item.absolute_path)))
        raise OperationError(details)


def required_capability(event_type: str) -> str:
    try:
        return EVENT_CAPABILITY[event_type]
    except KeyError as exc:
        raise OperationError(f"unknown operation type: {event_type}") from exc
