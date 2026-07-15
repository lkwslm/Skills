"""Strict adapter for the current OpenSpec repository and JSON interfaces."""

from __future__ import annotations

from pathlib import Path
import re
import unicodedata
from typing import Any

from .base import MAX_PROVIDER_FILES, ProviderAdapter, ProviderError, SCHEMA_VERSION, confined_relative, hash_bytes, hash_file, hash_json, load_yaml


CHANGE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ARTIFACT_STATES = {"done", "ready", "blocked"}
TASK_ITEM = re.compile(r"^- \[([ xX])\] ([A-Za-z0-9][A-Za-z0-9._-]*)\s+(.+?)\s*$")


class OpenSpecProvider(ProviderAdapter):
    provider = "openspec"
    executable_name = "openspec"
    version_args = ("--version",)

    def _require_string(self, value: object, where: str) -> str:
        if not isinstance(value, str) or not value:
            raise ProviderError("PROVIDER_DATA_INVALID", f"{where} must be a non-empty string", 2)
        return value

    def _artifact_paths(self, change_dir: Path, output_path: str, status: str) -> list[Path]:
        if Path(output_path).is_absolute() or ".." in Path(output_path).parts:
            raise ProviderError("PROVIDER_LAYOUT_INVALID", f"OpenSpec output path is unsafe: {output_path}")
        if any(character in output_path for character in "*?["):
            matches = sorted(path for path in change_dir.glob(output_path) if path.is_file())
            if len(matches) > MAX_PROVIDER_FILES:
                raise ProviderError("PROVIDER_LAYOUT_INVALID", "OpenSpec wildcard output expands to too many files")
            if status == "done" and not matches:
                raise ProviderError("PROVIDER_LAYOUT_INVALID", f"completed OpenSpec artifact has no files: {output_path}")
            return matches if status == "done" else []
        candidate = change_dir / output_path
        if status == "done":
            confined_relative(self.repo, candidate)
            return [candidate]
        try:
            candidate.resolve(strict=False).relative_to(self.repo)
            return []
        except ValueError as exc:
            raise ProviderError("PROVIDER_LAYOUT_INVALID", f"OpenSpec output path escapes repository: {output_path}") from exc

    def _task_items(self, path: Path, change_id: str) -> list[tuple[str, str, bytes]]:
        try:
            text = unicodedata.normalize(
                "NFC", path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
            )
        except (OSError, UnicodeDecodeError) as exc:
            raise ProviderError("PROVIDER_LAYOUT_INVALID", f"cannot read OpenSpec tasks for {change_id}: {exc}", 2) from exc
        result: list[tuple[str, str, bytes]] = []
        seen: set[str] = set()
        for line in text.splitlines():
            match = TASK_ITEM.fullmatch(line)
            if match is None:
                continue
            task_id = match.group(2)
            if task_id in seen:
                raise ProviderError("PROVIDER_DATA_INVALID", f"duplicate OpenSpec task ID for {change_id}: {task_id}", 2)
            seen.add(task_id)
            status = "done" if match.group(1).lower() == "x" else "ready"
            material = f"- [ ] {task_id} {match.group(3)}\n".encode("utf-8")
            result.append((task_id, status, material))
        if not result:
            raise ProviderError("PROVIDER_DATA_INVALID", f"OpenSpec tasks file has no standard checkbox tasks: {change_id}", 2)
        return result

    def detect(self) -> dict[str, Any]:
        config_path = self.repo / "openspec" / "config.yaml"
        config_uri = confined_relative(self.repo, config_path)
        if not config_path.is_file():
            raise ProviderError("PROVIDER_LAYOUT_INVALID", "OpenSpec requires openspec/config.yaml")
        config = load_yaml(config_path)
        configured_schema = self._require_string(config.get("schema"), "openspec/config.yaml schema")
        changes_root = self.repo / "openspec" / "changes"
        specs_root = self.repo / "openspec" / "specs"
        confined_relative(self.repo, changes_root)
        specs_uri = confined_relative(self.repo, specs_root)
        if not changes_root.is_dir() or not specs_root.is_dir():
            raise ProviderError("PROVIDER_LAYOUT_INVALID", "OpenSpec requires openspec/changes and openspec/specs")
        change_dirs = sorted(path for path in changes_root.iterdir() if path.is_dir() and path.name != "archive")
        if len(change_dirs) > MAX_PROVIDER_FILES:
            raise ProviderError("PROVIDER_LAYOUT_INVALID", "OpenSpec contains too many active changes")
        version = self.require_runtime()
        authorities: dict[str, dict[str, str]] = {
            "configuration": {"uri": config_uri, "writer": "openspec"},
            "specs": {"uri": specs_uri, "writer": "openspec"},
        }
        spec_files = [path for path in sorted(specs_root.rglob("*")) if path.is_file()]
        for path in spec_files:
            confined_relative(self.repo, path)
        if len(spec_files) > MAX_PROVIDER_FILES:
            raise ProviderError("PROVIDER_LAYOUT_INVALID", "OpenSpec contains too many spec files")
        mappings: dict[str, dict[str, Any]] = {}
        observations = {
            "configuration": hash_file(config_path),
            "specs": hash_json({
                confined_relative(self.repo, path): hash_file(path)
                for path in spec_files
            }),
        }
        for change_dir in change_dirs:
            confined_relative(self.repo, change_dir)
            change_id = change_dir.name
            if CHANGE_ID.fullmatch(change_id) is None:
                raise ProviderError("PROVIDER_LAYOUT_INVALID", f"invalid OpenSpec change ID: {change_id}")
            metadata_path = change_dir / ".openspec.yaml"
            metadata_uri = confined_relative(self.repo, metadata_path)
            if not metadata_path.is_file():
                raise ProviderError("PROVIDER_LAYOUT_INVALID", f"OpenSpec change lacks .openspec.yaml: {change_id}")
            metadata = load_yaml(metadata_path)
            change_schema = self._require_string(metadata.get("schema"), f"{change_id}/.openspec.yaml schema")
            if change_schema != configured_schema:
                raise ProviderError("PROVIDER_DATA_INVALID", f"OpenSpec schema mismatch for change {change_id}", 2)
            status = self.run_json(("status", "--change", change_id, "--json"))
            if status.get("changeName") != change_id or status.get("schemaName") != change_schema:
                raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"OpenSpec status identity mismatch for {change_id}")
            if not isinstance(status.get("isComplete"), bool) or not isinstance(status.get("applyRequires"), list):
                raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"OpenSpec status shape is invalid for {change_id}")
            artifacts = status.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"OpenSpec status has no artifacts for {change_id}")
            instructions = self.run_json(("instructions", "apply", "--change", change_id, "--json"))
            if instructions.get("changeName") != change_id or instructions.get("schemaName") != change_schema:
                raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"OpenSpec instructions identity mismatch for {change_id}")
            if instructions.get("state") not in {"ready", "blocked", "complete"}:
                raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"OpenSpec instructions state is invalid for {change_id}")
            if not isinstance(instructions.get("instruction"), str) or not instructions["instruction"]:
                raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"OpenSpec instructions are incomplete for {change_id}")
            native_change_id = f"openspec:change:{change_id}"
            mappings[native_change_id] = {
                "delivery_id": f"OPENSPEC-CHANGE-{change_id}",
                "native_id": change_id,
                "native_parent_id": None,
                "artifact_type": "change",
                "authority_uri": metadata_uri,
                "status": "done" if status["isComplete"] else "active",
                "content_hash": hash_file(metadata_path),
                "content_canonicalization": "raw-v1",
            }
            authorities[native_change_id] = {"uri": metadata_uri, "writer": "openspec"}
            observations[f"metadata:{change_id}"] = hash_file(metadata_path)
            observations[f"status:{change_id}"] = hash_json(status)
            observations[f"instructions:{change_id}"] = hash_json(instructions)
            seen_artifacts: set[str] = set()
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"OpenSpec artifact status must be an object for {change_id}")
                artifact_id = self._require_string(artifact.get("id"), f"OpenSpec artifact ID for {change_id}")
                output_path = self._require_string(artifact.get("outputPath"), f"OpenSpec outputPath for {change_id}/{artifact_id}")
                artifact_status = artifact.get("status")
                if artifact_status not in ARTIFACT_STATES:
                    raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"invalid OpenSpec artifact status for {change_id}/{artifact_id}")
                if artifact_id in seen_artifacts:
                    raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"duplicate OpenSpec artifact ID for {change_id}: {artifact_id}")
                seen_artifacts.add(artifact_id)
                if artifact_status == "blocked":
                    missing = artifact.get("missingDeps")
                    if not isinstance(missing, list) or not missing or not all(isinstance(item, str) and item for item in missing):
                        raise ProviderError("PROVIDER_CLI_OUTPUT_INVALID", f"blocked OpenSpec artifact lacks missingDeps: {change_id}/{artifact_id}")
                paths = self._artifact_paths(change_dir, output_path, artifact_status)
                observations[f"artifact-state:{change_id}:{artifact_id}"] = hash_json({
                    "output_path": output_path,
                    "status": artifact_status,
                    "missing_deps": artifact.get("missingDeps", []),
                })
                for index, path in enumerate(paths):
                    uri = confined_relative(self.repo, path)
                    if artifact_id == "tasks":
                        for task_id, task_status, material in self._task_items(path, change_id):
                            native_id = f"openspec:change:{change_id}:task:{task_id}"
                            delivery_suffix = re.sub(r"[^A-Za-z0-9]+", "-", task_id).strip("-")
                            mappings[native_id] = {
                                "delivery_id": f"OPENSPEC-{change_id}-task-{delivery_suffix}",
                                "native_id": f"task:{task_id}",
                                "native_parent_id": change_id,
                                "artifact_type": "task",
                                "authority_uri": uri,
                                "status": task_status,
                                "content_hash": hash_bytes(material),
                                "content_canonicalization": "utf8-nfc-lf-v1",
                                "content_selector": {"kind": "openspec-task-v1", "task_id": task_id},
                            }
                            authorities[native_id] = {"uri": uri, "writer": "openspec"}
                            observations[f"task:{change_id}:{task_id}"] = hash_bytes(material)
                        observations[f"artifact:{change_id}:{artifact_id}:{index + 1}"] = hash_file(path)
                        continue
                    suffix = "" if len(paths) == 1 and not any(character in output_path for character in "*?[") else f":file:{hash_json(uri)}"
                    native_id = f"openspec:change:{change_id}:{artifact_id}{suffix}"
                    mappings[native_id] = {
                        "delivery_id": f"OPENSPEC-{change_id}-{artifact_id}-{index + 1}",
                        "native_id": artifact_id if not suffix else f"{artifact_id}:{uri}",
                        "native_parent_id": change_id,
                        "artifact_type": artifact_id,
                        "authority_uri": uri,
                        "status": artifact_status,
                        "content_hash": hash_file(path),
                        "content_canonicalization": "raw-v1",
                    }
                    authorities[native_id] = {"uri": uri, "writer": "openspec"}
                    observations[f"artifact:{change_id}:{artifact_id}:{index + 1}"] = mappings[native_id]["content_hash"]
        return self.finalize_profile({
            "schema_version": SCHEMA_VERSION,
            "profile_id": "PROFILE-openspec",
            "profile_hash": "",
            "provider": "openspec",
            "mode": "native",
            "adapter_version": self.adapter_version,
            "version": version,
            "version_source": self.runtime["resolved_path"],
            "artifact_root": "openspec",
            "configuration": "openspec/config.yaml",
            "authorities": authorities,
            "id_mapping": mappings,
            "capabilities": ["artifact-graph", "instructions", "spec", "tasks"],
            "command_entrypoints": {
                "status": "openspec status --change <id> --json",
                "instructions": "openspec instructions apply --change <id> --json",
            },
            "runtime": self.runtime,
            "observations": observations,
            "trust": {"level": "trusted", "reasons": ["native layout and machine-readable state verified"]},
        })
