"""Authorization derived only from signed trust policy and reducer state."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping

from .events import required_capability


class PermissionDenied(ValueError):
    """The signed actor does not own the requested capability and scope."""


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PermissionDenied("authorization timestamps must be UTC")
    return parsed


def _path(raw: str) -> PurePosixPath:
    if not raw or "\\" in raw:
        raise PermissionDenied("authorized paths must be non-empty POSIX paths")
    value = PurePosixPath(raw)
    if value.is_absolute() or any(part in {"", ".", ".."} for part in value.parts):
        raise PermissionDenied("authorized paths must not be absolute or contain traversal")
    return value


def _covered(path: str, scopes: list[str]) -> bool:
    candidate = _path(path)
    for raw_scope in scopes:
        scope = _path(raw_scope)
        if candidate == scope or scope in candidate.parents:
            return True
    return False


def path_covered(path: str, scopes: list[str]) -> bool:
    """Return whether a repository-relative path is inside a signed scope."""
    return _covered(path, scopes)


def actor_record(state: Mapping[str, Any], actor_id: str) -> Mapping[str, Any]:
    policy = state.get("trust_policy")
    if not policy:
        raise PermissionDenied("trust policy is not initialized")
    matches = [item for item in policy["actors"] if item["actor_id"] == actor_id]
    if len(matches) != 1:
        raise PermissionDenied(f"actor is not uniquely trusted: {actor_id}")
    return matches[0]


def authorize_operation(
    state: Mapping[str, Any],
    operation: Mapping[str, Any],
    *,
    actor_id: str,
    signer_fingerprint: str,
    sequence: int,
    at: str,
) -> None:
    actor = actor_record(state, actor_id)
    if actor["key_fingerprint"] != signer_fingerprint:
        raise PermissionDenied("event signature key is not bound to the actor")
    now = _time(at)
    if _time(actor["valid_from"]) > now:
        raise PermissionDenied("actor key is not valid yet")
    if actor["valid_until"] is not None and _time(actor["valid_until"]) <= now:
        raise PermissionDenied("actor key is expired")
    revoked = actor["revoked_at_sequence"]
    if revoked is not None and sequence >= revoked:
        raise PermissionDenied("actor key is revoked")
    capability = required_capability(str(operation["type"]))
    if capability not in actor["capabilities"]:
        raise PermissionDenied(f"actor lacks capability {capability}")
    if capability == "trust.manage" and actor["key_fingerprint"] != state["trust_policy"]["root_key_fingerprint"]:
        raise PermissionDenied("only the externally anchored root key may change trust policy")
    payload = operation["payload"]
    is_root = actor["key_fingerprint"] == state["trust_policy"]["root_key_fingerprint"]
    roles = set(actor["roles"])
    if not is_root:
        required_roles = {
            "approval.write": {"human-approver"},
            "audit.write": {"verifier"},
            "evidence.write": {"implementer", "verifier"},
            "claim.write": {"human-approver", "implementer", "orchestrator", "verifier"},
            "state.write": {"human-approver", "implementer", "orchestrator", "verifier", "release-controller"},
            "provider.write": {"spec-integrator"},
            "migration.write": {"migration-controller"},
        }.get(capability)
        if required_roles is not None and roles.isdisjoint(required_roles):
            raise PermissionDenied(f"actor role does not own capability {capability}")
        if capability == "approval.write" and set(actor["capabilities"]) & {"artifact.write", "evidence.write", "audit.write"}:
            raise PermissionDenied("approver identity violates separation of duties")
        if capability == "audit.write" and not roles.isdisjoint({"fact-extractor", "spec-author", "contract-owner", "implementer"}):
            raise PermissionDenied("auditor identity violates separation of duties")
        if capability == "artifact.write":
            artifact_roles = {
                "source": {"fact-extractor"}, "requirement": {"fact-extractor", "spec-author"},
                "contract": {"contract-owner"}, "spec": {"spec-author"}, "task": {"spec-author"},
                "implementation": {"implementer"}, "test": {"implementer", "verifier"},
                "evidence": {"implementer", "verifier"}, "audit": {"verifier"},
                "context-package": {"fact-extractor", "orchestrator"},
                "spec-tool-profile": {"spec-integrator"}, "migration": {"migration-controller"},
            }
            artifact_type = payload["artifact"]["artifact_type"]
            if roles.isdisjoint(artifact_roles[artifact_type]):
                raise PermissionDenied(f"actor role cannot write artifact type {artifact_type}")
    paths: list[str] = []
    environment: str | None = None
    if operation["type"] in {"artifact_registered", "artifact_superseded"}:
        authority = payload["artifact"]["authority"]
        if authority["kind"] in {"git", "provider"}:
            paths.append(authority["path"])
    elif operation["type"] == "approval_recorded":
        paths.extend(payload["approval"]["scope"])
        environment = payload["approval"]["environment"]
    elif operation["type"] == "evidence_recorded":
        paths.extend(payload["evidence"]["scope"])
        environment = payload["evidence"]["environment"]
    elif operation["type"] == "audit_recorded":
        paths.extend(payload["audit"]["scope"])
        environment = payload["audit"]["environment"]
    elif operation["type"] == "state_transitioned":
        paths.extend(payload["transition"]["scope"])
        environment = payload["transition"]["environment"]
    if paths and any(not _covered(path, actor["path_scopes"]) for path in paths):
        raise PermissionDenied("operation path is outside the actor's signed trust-policy scope")
    if environment is not None and environment not in actor["environments"]:
        raise PermissionDenied("operation environment is outside the actor's signed trust-policy scope")


def require_active_claim(
    state: Mapping[str, Any],
    operation: Mapping[str, Any],
    *,
    actor_id: str,
    at: str,
) -> None:
    if operation["type"] != "state_transitioned":
        return
    payload = operation["payload"]
    transition = payload["transition"]
    claim = state.get("claims", {}).get(payload["claim_id"])
    if claim is None or claim.get("status") != "active":
        raise PermissionDenied("state transition requires an active claim")
    record = claim["record"]
    if record["holder_actor_id"] != actor_id:
        raise PermissionDenied("claim belongs to another actor")
    if record["task"] != transition["object"]:
        raise PermissionDenied("claim is bound to a different object/version/digest")
    if record["lease_token"] != payload["lease_token"] or record["fencing_token"] != payload["fencing_token"]:
        raise PermissionDenied("claim lease or fencing token is stale")
    if _time(at) < _time(record["acquired_at"]) or _time(record["expires_at"]) <= _time(at):
        raise PermissionDenied("claim is expired and must be explicitly expired before reacquisition")
