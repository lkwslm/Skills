"""Strict adapter for Spec Kit workflow state."""

from __future__ import annotations

import re
from typing import Any

from .base import MAX_PROVIDER_FILES, ProviderAdapter, ProviderError, SCHEMA_VERSION, confined_relative, hash_file, hash_json, load_json, load_jsonl


RUN_STATES = {"created", "running", "completed", "paused", "failed", "aborted"}
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SpecKitProvider(ProviderAdapter):
    provider = "spec-kit"
    executable_name = "specify"
    version_args = ("version",)

    def _validate_integration(self, value: dict[str, Any]) -> None:
        default = value.get("default_integration")
        installed = value.get("installed_integrations")
        settings = value.get("integration_settings")
        schema = value.get("integration_state_schema")
        if not isinstance(default, str) or not default:
            raise ProviderError("PROVIDER_DATA_INVALID", "Spec Kit default_integration is missing", 2)
        if not isinstance(installed, list) or not installed or not all(isinstance(item, str) and item for item in installed):
            raise ProviderError("PROVIDER_DATA_INVALID", "Spec Kit installed_integrations is invalid", 2)
        if default not in installed or len(set(installed)) != len(installed):
            raise ProviderError("PROVIDER_DATA_INVALID", "Spec Kit integration set is inconsistent", 2)
        if not isinstance(settings, dict) or isinstance(schema, bool) or not isinstance(schema, (str, int)) or not str(schema):
            raise ProviderError("PROVIDER_DATA_INVALID", "Spec Kit integration metadata is incomplete", 2)

    def _validate_state(self, state: dict[str, Any], run_id: str) -> None:
        if state.get("run_id") != run_id:
            raise ProviderError("PROVIDER_DATA_INVALID", f"Spec Kit run_id does not match directory: {run_id}", 2)
        if not isinstance(state.get("workflow_id"), str) or not state["workflow_id"]:
            raise ProviderError("PROVIDER_DATA_INVALID", f"Spec Kit workflow_id is invalid: {run_id}", 2)
        if state.get("status") not in RUN_STATES:
            raise ProviderError("PROVIDER_DATA_INVALID", f"Spec Kit run status is invalid: {run_id}", 2)
        if state.get("current_step_id") is not None and (not isinstance(state["current_step_id"], str) or not state["current_step_id"]):
            raise ProviderError("PROVIDER_DATA_INVALID", f"Spec Kit current_step_id is invalid: {run_id}", 2)
        index = state.get("current_step_index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ProviderError("PROVIDER_DATA_INVALID", f"Spec Kit current_step_index is invalid: {run_id}", 2)

    def detect(self) -> dict[str, Any]:
        integration_path = self.repo / ".specify" / "integration.json"
        integration_uri = confined_relative(self.repo, integration_path)
        if not integration_path.is_file():
            raise ProviderError("PROVIDER_LAYOUT_INVALID", "Spec Kit requires .specify/integration.json")
        integration = load_json(integration_path)
        self._validate_integration(integration)
        runs_root = self.repo / ".specify" / "workflows" / "runs"
        confined_relative(self.repo, runs_root)
        if not runs_root.is_dir():
            raise ProviderError("PROVIDER_LAYOUT_INVALID", "Spec Kit workflow runs directory is missing")
        run_dirs = sorted(path for path in runs_root.iterdir() if path.is_dir())
        if len(run_dirs) > MAX_PROVIDER_FILES:
            raise ProviderError("PROVIDER_LAYOUT_INVALID", "Spec Kit contains too many persisted workflow runs")
        if not run_dirs:
            raise ProviderError("PROVIDER_LAYOUT_INVALID", "Spec Kit has no persisted workflow runs")
        version = self.require_runtime()
        integration_status = self.run_json(("integration", "status", "--json"))
        if integration_status.get("status") not in {"ok", "warning"}:
            raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", "Spec Kit integration status is not healthy")
        if integration_status.get("default_integration") != integration["default_integration"]:
            raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", "Spec Kit CLI default integration differs from integration.json")
        reported_installed = integration_status.get("installed_integrations")
        if not isinstance(reported_installed, list) or reported_installed != integration["installed_integrations"]:
            raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", "Spec Kit CLI installed integrations differ from integration.json")
        authorities: dict[str, dict[str, str]] = {
            "integration": {"uri": integration_uri, "writer": "spec-kit"},
        }
        mappings: dict[str, dict[str, Any]] = {}
        observations = {
            "integration": hash_file(integration_path),
            "cli-integration-status": hash_json(integration_status),
        }
        for run_dir in run_dirs:
            confined_relative(self.repo, run_dir)
            run_id = run_dir.name
            if RUN_ID.fullmatch(run_id) is None:
                raise ProviderError("PROVIDER_LAYOUT_INVALID", f"invalid Spec Kit run ID: {run_id}")
            required = {name: run_dir / name for name in ("state.json", "inputs.json", "log.jsonl")}
            for path in required.values():
                confined_relative(self.repo, path)
            missing = [name for name, path in required.items() if not path.is_file()]
            if missing:
                raise ProviderError("PROVIDER_LAYOUT_INVALID", f"Spec Kit run {run_id} lacks: {', '.join(missing)}")
            state = load_json(required["state.json"])
            inputs = load_json(required["inputs.json"])
            log_records = load_jsonl(required["log.jsonl"])
            self._validate_state(state, run_id)
            cli_state = self.run_json(("workflow", "status", run_id, "--json"))
            for field in ("run_id", "workflow_id", "status", "current_step_id", "current_step_index"):
                if cli_state.get(field) != state.get(field):
                    raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"Spec Kit CLI state differs from state.json for {run_id}: {field}")
            if not all(isinstance(record, dict) for record in log_records):
                raise ProviderError("PROVIDER_DATA_INVALID", f"Spec Kit log contains invalid records: {run_id}", 2)
            state_uri = confined_relative(self.repo, required["state.json"])
            inputs_uri = confined_relative(self.repo, required["inputs.json"])
            log_uri = confined_relative(self.repo, required["log.jsonl"])
            native_id = f"spec-kit:run:{run_id}"
            mappings[native_id] = {
                "delivery_id": f"SPECKIT-RUN-{run_id}",
                "native_id": run_id,
                "native_parent_id": state["workflow_id"],
                "artifact_type": "workflow-run",
                "authority_uri": state_uri,
                "status": state["status"],
                "content_hash": hash_json(state),
            }
            authorities[f"run:{run_id}:state"] = {"uri": state_uri, "writer": "spec-kit"}
            authorities[f"run:{run_id}:inputs"] = {"uri": inputs_uri, "writer": "spec-kit"}
            authorities[f"run:{run_id}:log"] = {"uri": log_uri, "writer": "spec-kit"}
            observations[f"state:{run_id}"] = hash_json(state)
            observations[f"inputs:{run_id}"] = hash_json(inputs)
            observations[f"log:{run_id}"] = hash_file(required["log.jsonl"])
            observations[f"cli-status:{run_id}"] = hash_json(cli_state)
        return self.finalize_profile({
            "schema_version": SCHEMA_VERSION,
            "profile_id": "PROFILE-spec-kit",
            "profile_hash": "",
            "provider": "spec-kit",
            "mode": "native",
            "adapter_version": self.adapter_version,
            "version": version,
            "version_source": self.runtime["resolved_path"],
            "artifact_root": ".specify",
            "configuration": ".specify/integration.json",
            "authorities": authorities,
            "id_mapping": mappings,
            "capabilities": ["workflow-inputs", "workflow-log", "workflow-resume", "workflow-state"],
            "command_entrypoints": {
                "integration-status": "specify integration status --json",
                "workflow-status": "specify workflow status <run-id> --json",
            },
            "runtime": self.runtime,
            "observations": observations,
            "trust": {"level": "trusted", "reasons": ["persisted run state and machine-readable status verified"]},
        })
