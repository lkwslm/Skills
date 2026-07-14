"""Strict JSON Schema loading and validation for versioned delivery records."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
    from referencing import Registry, Resource
except ImportError as exc:  # pragma: no cover - exercised in dependency-isolation tests
    raise RuntimeError("required dependency unavailable: jsonschema and referencing") from exc

from .canonical import loads_strict


class SchemaValidationError(ValueError):
    """A schema or a document validated by it is invalid."""


def _format_path(parts: Iterable[Any]) -> str:
    result = "$"
    for part in parts:
        result += "[{}]".format(part) if isinstance(part, int) else "." + str(part)
    return result


def validate(instance: Any, schema: Dict[str, Any]) -> None:
    """Validate one instance and raise all deterministic validation errors."""
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SchemaValidationError("invalid JSON Schema: " + exc.message) from exc
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda item: (tuple(str(part) for part in item.absolute_path), item.message),
    )
    if errors:
        details = [
            _format_path(error.absolute_path) + ": " + error.message
            for error in errors
        ]
        raise SchemaValidationError("; ".join(details))


class SchemaRegistry:
    """Load only explicitly supported, versioned schemas from one directory."""

    def __init__(self, root: Path, supported_version: str = "1.0") -> None:
        self.root = Path(root).resolve()
        self.supported_version = supported_version
        if not self.root.is_dir():
            raise SchemaValidationError("schema directory does not exist: " + str(root))
        self._schemas: Dict[str, Dict[str, Any]] = {}
        self._registry = Registry()
        self._load_all()

    def _load_all(self) -> None:
        identifiers = set()
        for path in sorted(self.root.glob("*.schema.json")):
            name = path.name[: -len(".schema.json")]
            try:
                value = loads_strict(path.read_bytes())
            except OSError as exc:
                raise SchemaValidationError("cannot read schema: " + str(path)) from exc
            if not isinstance(value, dict):
                raise SchemaValidationError("schema root must be an object: " + name)
            try:
                Draft202012Validator.check_schema(value)
                resource = Resource.from_contents(value)
            except Exception as exc:
                raise SchemaValidationError("invalid JSON Schema {}: {}".format(name, exc)) from exc
            identifiers_for_schema = {path.name, path.resolve().as_uri()}
            schema_id = value.get("$id")
            if isinstance(schema_id, str) and schema_id:
                identifiers_for_schema.add(schema_id)
            duplicate = identifiers & identifiers_for_schema
            if duplicate:
                raise SchemaValidationError(
                    "duplicate schema identifier: " + sorted(duplicate)[0]
                )
            identifiers.update(identifiers_for_schema)
            for identifier in identifiers_for_schema:
                self._registry = self._registry.with_resource(identifier, resource)
            self._schemas[name] = value

    def schema(self, name: str) -> Dict[str, Any]:
        if not name or Path(name).name != name:
            raise SchemaValidationError("schema name must be a simple file stem")
        if name not in self._schemas:
            raise SchemaValidationError("unknown schema: " + name)
        return self._schemas[name]

    def validate(self, name: str, instance: Any) -> None:
        if not isinstance(instance, dict):
            raise SchemaValidationError("versioned document root must be an object")
        version = instance.get("schema_version")
        if version != self.supported_version:
            raise SchemaValidationError(
                "unsupported schema_version {!r}; expected {!r}".format(
                    version, self.supported_version
                )
            )
        schema = self.schema(name)
        validator = Draft202012Validator(schema, registry=self._registry)
        errors = sorted(
            validator.iter_errors(instance),
            key=lambda item: (
                tuple(str(part) for part in item.absolute_path),
                item.message,
            ),
        )
        if errors:
            raise SchemaValidationError(
                "; ".join(
                    _format_path(error.absolute_path) + ": " + error.message
                    for error in errors
                )
            )

    def load_and_validate(self, name: str, path: Path) -> Dict[str, Any]:
        try:
            value = loads_strict(Path(path).read_bytes())
        except OSError as exc:
            raise SchemaValidationError("cannot read document: " + str(path)) from exc
        self.validate(name, value)
        return value
