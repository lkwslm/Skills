"""Exact, relation-aware traceability closure policies."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


class TraceabilityError(ValueError):
    pass


def _key(identity: Mapping[str, Any]) -> str:
    return f"{identity['artifact_id']}@{identity['version']}"


def _targets(
    state: Mapping[str, Any], frontier: set[str], relation: str, target_type: str
) -> set[str]:
    nodes = state["trace_nodes"]
    result: set[str] = set()
    for edge in state["trace_edges"].values():
        source, target = _key(edge["from"]), _key(edge["to"])
        if (
            source in frontier
            and edge["relation"] == relation
            and target in nodes
            and nodes[target]["node_type"] == target_type
            and nodes[source]["node"] == edge["from"]
            and nodes[target]["node"] == edge["to"]
        ):
            result.add(target)
    return result


def _reachable(state: Mapping[str, Any], start: set[str], steps: Sequence[tuple[str, str]]) -> set[str]:
    frontier = set(start)
    for relation, target_type in steps:
        frontier = _targets(state, frontier, relation, target_type)
        if not frontier:
            break
    return frontier


def validate_completion_closure(
    state: Mapping[str, Any],
    suite: str,
    subject: Mapping[str, Any],
    run_inputs: Sequence[Mapping[str, Any]],
    evidence_identities: Sequence[Mapping[str, Any]],
    audit_identities: Sequence[Mapping[str, Any]],
) -> None:
    nodes = state["trace_nodes"]
    subject_key = _key(subject)
    subject_node = nodes.get(subject_key)
    if subject_node is None or subject_node["node"] != subject:
        raise TraceabilityError("completion subject has no exact governed trace node")
    evidence_keys = {_key(item) for item in evidence_identities}
    audit_keys = {_key(item) for item in audit_identities}
    if not evidence_keys or not audit_keys:
        raise TraceabilityError("completion requires exact evidence and audit gate identities")
    for identity in [*evidence_identities, *audit_identities]:
        if nodes.get(_key(identity), {}).get("node") != identity:
            raise TraceabilityError("completion gate identity has no exact governed trace node")

    roots = {key for key, value in nodes.items() if value["node_type"] in {"requirement", "contract"}}
    if subject_node["node_type"] == "context-package":
        roots &= _targets(state, {subject_key}, "derives", "requirement") | _targets(state, {subject_key}, "derives", "contract")
    elif subject_node["node_type"] in {"requirement", "contract"}:
        roots &= {subject_key}
    elif subject_node["node_type"] != "task":
        raise TraceabilityError("completion subject type cannot own this lifecycle")
    if not roots:
        raise TraceabilityError("completion requires at least one governed requirement or contract node")
    anchored_roots: set[str] = set()
    for root in roots:
        tasks = _reachable(state, {root}, [("specifies", "spec"), ("derives", "task")])
        if subject_node["node_type"] == "task":
            tasks &= {subject_key}
        for task in tasks:
            evidences = _reachable(
                state, {task},
                [("implements", "implementation"), ("derives", "test"), ("verifies", "evidence")],
            ) & evidence_keys
            audits = _targets(state, evidences, "audits", "audit") & audit_keys
            if evidences and audits:
                anchored_roots.add(root)
                break
    if not anchored_roots or (subject_node["node_type"] == "context-package" and anchored_roots != roots):
        raise TraceabilityError("completion has no exact subject→evidence→audit trace closure")

    if suite == "brownfield":
        context_keys = {
            _key(identity) for identity in run_inputs
            if nodes.get(_key(identity), {}).get("node") == identity
            and nodes[_key(identity)]["node_type"] == "context-package"
        }
        if subject_node["node_type"] == "context-package" and subject_key not in context_keys:
            raise TraceabilityError("brownfield context subject is absent from the exact run inputs")
        if not context_keys:
            raise TraceabilityError("brownfield completion requires an exact context-package run input")
        for context_key in context_keys:
            current = _targets(state, {context_key}, "derives", "current-behavior")
            if not current:
                raise TraceabilityError("brownfield context package has no current-behavior root")
            for key in current:
                target = _reachable(
                    state, {key},
                    [("migrates", "migration-plan"), ("migrates", "target-behavior"),
                     ("observes", "observation-plan"), ("stops", "stop-condition")],
                )
                preserved = _reachable(state, {key}, [("preserves", "unchanged-behavior")])
                if not target or not preserved:
                    raise TraceabilityError(f"brownfield migration, observation, or preservation closure is incomplete for {key}")
