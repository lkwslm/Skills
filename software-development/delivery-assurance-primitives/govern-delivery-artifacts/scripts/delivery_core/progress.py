"""Build a deterministic, resumable delivery progress view from replayed state."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


def _identity(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": artifact["artifact_id"],
        "version": artifact["version"],
        "digest": artifact["digest"],
    }


def _identity_key(identity: Mapping[str, Any]) -> str:
    return f"{identity['artifact_id']}@{identity['version']}"


def build_progress(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return current tasks, dependencies, claims, providers, and trace coverage."""
    profiles: dict[str, Mapping[str, Any]] = {}
    for entry in state["provider_profiles"].values():
        record = entry["record"]
        current = profiles.get(record["profile_id"])
        marker = (record["observed_at"], record["version"])
        if current is None or marker > (current["record"]["observed_at"], current["record"]["version"]):
            profiles[record["profile_id"]] = entry

    active_claims: dict[str, dict[str, Any]] = {}
    for claim_id, entry in state["claims"].items():
        if entry["status"] == "active":
            active_claims[_identity_key(entry["record"]["task"])] = {
                "claim_id": claim_id,
                "holder_actor_id": entry["record"]["holder_actor_id"],
                "fencing_token": entry["record"]["fencing_token"],
                "expires_at": entry["record"]["expires_at"],
            }

    tasks: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    for artifact_id, version in sorted(state["current_versions"].items()):
        key = f"{artifact_id}@{version}"
        artifact = state["artifacts"][key]
        if artifact["artifact_type"] != "task":
            continue
        task_state = state["states"].get(key)
        current_state = task_state["current_state"] if task_state is not None else None
        state_counts[current_state or "untracked"] += 1
        dependencies: list[dict[str, Any]] = []
        blocked_by: list[dict[str, Any]] = []
        for dependency in artifact["derived_from"]:
            dependency_key = _identity_key(dependency)
            dependency_artifact = state["artifacts"].get(dependency_key)
            if dependency_artifact is None or dependency_artifact["artifact_type"] != "task":
                continue
            dependency_state = state["states"].get(dependency_key)
            value = {
                "identity": dependency,
                "state": dependency_state["current_state"] if dependency_state is not None else None,
            }
            dependencies.append(value)
            if value["state"] != "accepted":
                blocked_by.append(value)
        claim = active_claims.get(key)
        provider_status = None
        authority = artifact["authority"]
        if authority["kind"] == "provider":
            latest = profiles.get(authority["profile_id"])
            if latest is not None:
                mapping = latest["record"]["id_mapping"].get(authority["native_id"])
                provider_status = "missing" if mapping is None else mapping["status"]
        provider_complete = provider_status in {"done", "completed"}
        if provider_complete and current_state != "accepted":
            alignment = "provider_complete_delivery_open"
        elif current_state == "accepted" and provider_status not in {None, "done", "completed"}:
            alignment = "delivery_accepted_provider_open"
        else:
            alignment = "aligned"
        ready = (
            artifact["status"] == "active"
            and current_state == "approved"
            and not blocked_by
            and claim is None
            and not provider_complete
        )
        tasks.append({
            "identity": _identity(artifact),
            "artifact_status": artifact["status"],
            "provider_status": provider_status,
            "delivery_state": current_state,
            "alignment": alignment,
            "dependencies": dependencies,
            "blocked_by": blocked_by,
            "active_claim": claim,
            "ready": ready,
        })

    providers = [
        {
            "profile_id": entry["record"]["profile_id"],
            "version": entry["record"]["version"],
            "digest": entry["digest"],
            "provider": entry["record"]["provider"],
            "commit": entry["record"]["commit"],
            "observed_at": entry["record"]["observed_at"],
            "native_objects": len(entry["record"]["id_mapping"]),
        }
        for _, entry in sorted(profiles.items())
    ]

    return {
        "providers": providers,
        "tasks": tasks,
        "ready_task_ids": [task["identity"]["artifact_id"] for task in tasks if task["ready"]],
        "task_state_counts": dict(sorted(state_counts.items())),
        "alignment_counts": dict(sorted(Counter(task["alignment"] for task in tasks).items())),
        "trace": {
            "nodes": len(state["trace_nodes"]),
            "edges": len(state["trace_edges"]),
        },
        "counts": {
            "current_artifacts": len(state["current_versions"]),
            "tasks": len(tasks),
            "active_claims": len(active_claims),
            "runs": len(state["runs"]),
            "evidence": len(state["evidence"]),
            "audits": len(state["audits"]),
        },
    }
