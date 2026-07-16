"""Build deterministic provider observation and artifact operations."""

from __future__ import annotations

import heapq
from pathlib import PurePosixPath
from typing import Any, Mapping

from .authority import digest_bytes
from .canonical import canonical_json_bytes, sha256_hex
from .gates import record_digest


class ProviderSyncError(ValueError):
    """A provider observation cannot be reconciled with governed state."""


class ProviderSyncConflict(ValueError):
    """A valid observation conflicts with already governed identities."""


_ARTIFACT_TYPES = {
    "change": "spec",
    "proposal": "spec",
    "spec": "spec",
    "specs": "spec",
    "design": "spec",
    "plan": "spec",
    "task": "task",
    "tasks": "task",
    "workflow-run": "task",
}


def _profile_version(profile: Mapping[str, Any], repository_uri: str, commit: str) -> str:
    material = canonical_json_bytes({
        "profile_hash": profile.get("profile_hash"),
        "repository_uri": repository_uri,
        "commit": commit,
    })
    return "obs-" + sha256_hex(material)[:20]


def _identity(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": artifact["artifact_id"],
        "version": artifact["version"],
        "digest": artifact["digest"],
    }


def _mapping_graph(
    mappings: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], dict[str, str | None]]:
    native_roots: dict[str, list[str]] = {}
    for key, item in mappings.items():
        native_roots.setdefault(str(item["native_id"]), []).append(key)
    parents: dict[str, str | None] = {}
    for key, item in mappings.items():
        parent_id = item.get("native_parent_id")
        if parent_id is None or parent_id not in native_roots:
            parents[key] = None
            continue
        candidates = native_roots[parent_id]
        if len(candidates) != 1:
            raise ProviderSyncError(f"provider parent ID is ambiguous: {parent_id}")
        parents[key] = candidates[0]
    children = {key: [] for key in mappings}
    indegree = {key: 0 for key in mappings}
    for key, parent in parents.items():
        if parent is not None:
            children[parent].append(key)
            indegree[key] = 1
    ready = [key for key, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        key = heapq.heappop(ready)
        ordered.append(key)
        for child in children[key]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    if len(ordered) != len(mappings):
        raise ProviderSyncError("provider native parent graph contains a cycle")
    return ordered, parents


def _profile_entry(state: Mapping[str, Any], authority: Mapping[str, Any]) -> Mapping[str, Any]:
    key = f"{authority.get('profile_id')}@{authority.get('profile_version')}"
    entry = state["provider_profiles"].get(key)
    if entry is None or entry.get("digest") != authority.get("profile_digest"):
        raise ProviderSyncConflict("current provider artifact does not resolve to its signed profile")
    return entry


def _mapping_changed(
    state: Mapping[str, Any], current: Mapping[str, Any], native_key: str, mapping: Mapping[str, Any]
) -> bool:
    authority = current["authority"]
    if authority.get("kind") != "provider":
        return True
    entry = _profile_entry(state, authority)
    previous = entry["record"]["id_mapping"].get(native_key)
    identity_mapping = {key: value for key, value in mapping.items() if key != "status"}
    previous_identity = (
        {key: value for key, value in previous.items() if key != "status"}
        if isinstance(previous, Mapping) else None
    )
    return previous_identity != identity_mapping or current["digest"] != {
        "algorithm": "sha256",
        "canonicalization": mapping["content_canonicalization"],
        "value": mapping["content_hash"],
    }


def build_provider_operations(
    state: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    repository_uri: str,
    commit: str,
    at: str,
    operation_id_prefix: str,
) -> tuple[list[dict[str, Any]], bytes | None, dict[str, int]]:
    """Return one profile observation plus the minimal artifact reconciliation batch."""
    if observed.get("schema_version") != "1.0" or observed.get("mode") != "native":
        raise ProviderSyncError("provider observation must be schema 1.0 in native mode")
    profile_id = observed.get("profile_id")
    mappings = observed.get("id_mapping")
    if not isinstance(profile_id, str) or not profile_id or not isinstance(mappings, dict):
        raise ProviderSyncError("provider observation lacks profile identity or native mappings")
    artifact_root = observed.get("artifact_root")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise ProviderSyncError("provider observation lacks an artifact root")
    root_path = PurePosixPath(artifact_root)
    if root_path.is_absolute() or any(part in {"", ".", ".."} for part in root_path.parts):
        raise ProviderSyncError("provider artifact root is unsafe")
    for native_key, item in mappings.items():
        if not isinstance(item, dict):
            raise ProviderSyncError(f"provider mapping is not an object: {native_key}")
        authority_path = PurePosixPath(str(item.get("authority_uri", "")))
        if authority_path.is_absolute() or tuple(authority_path.parts[:len(root_path.parts)]) != root_path.parts:
            raise ProviderSyncError(f"provider authority escapes its artifact root: {native_key}")
    delivery_ids = [item.get("delivery_id") for item in mappings.values()]
    if len(delivery_ids) != len(mappings) or any(not isinstance(item, str) or not item for item in delivery_ids):
        raise ProviderSyncError("provider mapping contains an invalid delivery ID")
    if len(set(delivery_ids)) != len(delivery_ids):
        raise ProviderSyncError("provider mapping contains duplicate delivery IDs")

    observation = canonical_json_bytes(dict(observed))
    observation_digest = digest_bytes(observation, "raw-v1")
    known_blob = any(
        entry["record"]["observation_authority"]["digest"] == observation_digest
        for entry in state["provider_profiles"].values()
    )
    matching = [
        entry for entry in state["provider_profiles"].values()
        if entry["record"]["profile_id"] == profile_id
        and entry["record"]["repository_uri"] == repository_uri
        and entry["record"]["observation_authority"]["digest"] == observation_digest
    ]
    operations: list[dict[str, Any]] = []
    if matching:
        active_profile = matching[-1]
        profile_record = active_profile["record"]
        profile_digest = active_profile["digest"]
        observation_blob = None
        profile_created = False
    else:
        version = _profile_version(observed, repository_uri, commit)
        key = f"{profile_id}@{version}"
        if key in state["provider_profiles"]:
            raise ProviderSyncConflict("deterministic provider profile version collides with existing state")
        profile_record = {
            "schema_version": "1.0",
            "profile_id": profile_id,
            "version": version,
            "provider": observed.get("provider"),
            "mode": "native",
            "provider_version": observed.get("version"),
            "repository_uri": repository_uri,
            "commit": commit,
            "id_mapping": mappings,
            "observation_authority": {
                "schema_version": "1.0",
                "kind": "delivery_blob",
                "digest": observation_digest,
            },
            "observed_at": at,
        }
        profile_digest = record_digest(profile_record)
        observation_blob = None if known_blob else observation
        profile_created = True
        operations.append({
            "schema_version": "1.0",
            "operation_id": f"{operation_id_prefix}:profile",
            "type": "provider_profile_observed",
            "payload": {"profile": profile_record},
        })

    active_mappings = profile_record["id_mapping"]
    managed_ids = {
        item["delivery_id"] for item in active_mappings.values() if item.get("content_hash") is not None
    }
    resolved: dict[str, dict[str, Any]] = {}
    counts = {"profiles": int(profile_created), "registered": 0, "superseded": 0, "deprecated": 0}
    order, parents = _mapping_graph(active_mappings)
    native_by_delivery = {item["delivery_id"]: key for key, item in active_mappings.items()}

    for index, native_key in enumerate(order, 1):
        mapping = active_mappings[native_key]
        content_hash = mapping.get("content_hash")
        if content_hash is None:
            continue
        canonicalization = mapping.get("content_canonicalization")
        if canonicalization not in {"raw-v1", "utf8-nfc-lf-v1", "delivery-json-v1"}:
            raise ProviderSyncError(f"provider mapping has no supported canonicalization: {native_key}")
        delivery_id = mapping["delivery_id"]
        current_version = state["current_versions"].get(delivery_id)
        current = state["artifacts"].get(f"{delivery_id}@{current_version}") if current_version else None
        if current is not None:
            authority = current["authority"]
            if authority.get("kind") != "provider" or authority.get("profile_id") != profile_id:
                raise ProviderSyncConflict(f"provider mapping would take over an existing artifact ID: {delivery_id}")
            if not _mapping_changed(state, current, native_key, mapping):
                resolved[native_key] = _identity(current)
                continue
        artifact_type = _ARTIFACT_TYPES.get(str(mapping["artifact_type"]))
        if artifact_type is None:
            raise ProviderSyncError(f"provider artifact type has no delivery mapping: {mapping['artifact_type']}")
        authority = {
            "schema_version": "1.0",
            "kind": "provider",
            "profile_id": profile_record["profile_id"],
            "profile_version": profile_record["version"],
            "profile_digest": profile_digest,
            "native_id": native_key,
            "artifact_kind": mapping["artifact_type"],
            "repository_uri": profile_record["repository_uri"],
            "commit": profile_record["commit"],
            "path": mapping["authority_uri"],
        }
        digest = {
            "algorithm": "sha256",
            "canonicalization": canonicalization,
            "value": content_hash,
        }
        parent_identity = resolved.get(parents[native_key]) if parents[native_key] is not None else None
        retained = [] if current is None else [
            item for item in current["derived_from"] if item["artifact_id"] not in native_by_delivery
        ]
        derived_from = retained + ([parent_identity] if parent_identity is not None else [])
        version = "provider-" + profile_record["version"]
        artifact_key = f"{delivery_id}@{version}"
        if artifact_key in state["artifacts"] and (current is None or artifact_key != f"{delivery_id}@{current['version']}"):
            raise ProviderSyncConflict(f"deterministic provider artifact version collides: {artifact_key}")
        artifact = {
            "schema_version": "1.0",
            "artifact_id": delivery_id,
            "artifact_type": artifact_type,
            "version": version,
            "digest": digest,
            "authority": authority,
            "derived_from": derived_from,
            "status": "active",
            "created_at": at,
        }
        if current is None:
            operation_type = "artifact_registered"
            payload = {"artifact": artifact}
            counts["registered"] += 1
        else:
            operation_type = "artifact_superseded"
            payload = {"artifact_id": delivery_id, "previous_version": current["version"], "artifact": artifact}
            counts["superseded"] += 1
        operations.append({
            "schema_version": "1.0",
            "operation_id": f"{operation_id_prefix}:artifact:{index}",
            "type": operation_type,
            "payload": payload,
        })
        resolved[native_key] = _identity(artifact)

    for delivery_id, current_version in sorted(state["current_versions"].items()):
        if delivery_id in managed_ids:
            continue
        current = state["artifacts"][f"{delivery_id}@{current_version}"]
        authority = current["authority"]
        if authority.get("kind") != "provider" or authority.get("profile_id") != profile_id or current["status"] == "deprecated":
            continue
        artifact = dict(current)
        artifact["version"] = "deprecated-" + profile_record["version"]
        artifact_key = f"{delivery_id}@{artifact['version']}"
        if artifact_key in state["artifacts"] and artifact_key != f"{delivery_id}@{current['version']}":
            raise ProviderSyncConflict(f"deterministic provider artifact version collides: {artifact_key}")
        artifact["status"] = "deprecated"
        artifact["created_at"] = at
        operations.append({
            "schema_version": "1.0",
            "operation_id": f"{operation_id_prefix}:deprecated:{counts['deprecated'] + 1}",
            "type": "artifact_superseded",
            "payload": {"artifact_id": delivery_id, "previous_version": current["version"], "artifact": artifact},
        })
        counts["deprecated"] += 1

    return operations, observation_blob, counts
