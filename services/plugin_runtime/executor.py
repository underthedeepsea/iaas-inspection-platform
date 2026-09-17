from enum import Enum

from jsonschema import SchemaError, ValidationError, validate

from .exec_executor import ExecExecutor
from .errors import PluginExecutionError, ReadOnlyCapabilityError
from .mcp_executor import McpExecutor
from .rest_executor import RestExecutor
from .rule_executor import RuleExecutor


class InputValidationError(PluginExecutionError):
    pass


class InvalidExecutionOriginError(PluginExecutionError):
    pass


OriginError = InvalidExecutionOriginError
ExecutionOriginError = InvalidExecutionOriginError
InvalidOriginError = InvalidExecutionOriginError


class ExecutionOrigin(str, Enum):
    CODE = "CODE"
    LLM = "LLM"


def normalize_origin(origin=None, *, llm=None):
    if llm is not None:
        if type(llm) is not bool:
            raise InvalidExecutionOriginError("execution origin legacy flag must be a boolean")
        legacy_origin = ExecutionOrigin.LLM if llm else ExecutionOrigin.CODE
        if origin is None:
            return legacy_origin
        normalized = normalize_origin(origin)
        if normalized is not legacy_origin:
            raise InvalidExecutionOriginError("execution origin conflicts with the legacy flag")
        return normalized

    if origin is None:
        return ExecutionOrigin.CODE
    if isinstance(origin, ExecutionOrigin):
        return origin
    if type(origin) is str:
        try:
            return ExecutionOrigin(origin)
        except ValueError as exc:
            raise InvalidExecutionOriginError("unsupported execution origin") from exc
    raise InvalidExecutionOriginError("unsupported execution origin")


class PluginExecutor:
    def __init__(self, *, rule_executor=None, exec_executor=None, rest_executor=None, mcp_executor=None):
        self.executors = {
            "RULE": rule_executor or RuleExecutor(),
            "EXEC": exec_executor or ExecExecutor(),
            "REST": rest_executor or RestExecutor(),
            "MCP": mcp_executor or McpExecutor(),
        }

    def execute(self, capability_version, payload, *, llm=None, origin=None):
        execution_origin = normalize_origin(origin, llm=llm)
        if capability_version.implementation_type == "EXEC" and capability_version.capability.read_only is not True:
            raise ReadOnlyCapabilityError("EXEC capabilities require a read-only capability")
        if execution_origin is ExecutionOrigin.LLM and capability_version.capability.read_only is not True:
            raise ReadOnlyCapabilityError("LLM execution requires a read-only capability")
        try:
            validate(payload, capability_version.input_schema)
        except (ValidationError, SchemaError, TypeError) as exc:
            detail = getattr(exc, "message", str(exc))
            raise InputValidationError(f"input schema validation failed: {detail}") from exc

        try:
            executor = self.executors[capability_version.implementation_type]
        except KeyError as exc:
            raise PluginExecutionError("unsupported plugin implementation type") from exc
        return executor.execute(capability_version, payload)
