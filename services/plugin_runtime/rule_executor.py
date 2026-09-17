class RuleExecutionError(ValueError):
    pass


class RuleExecutor:
    def execute(self, capability_version, payload):
        rule = capability_version.manifest.get("rule", {})
        conditions = rule.get("all")
        if not isinstance(conditions, list):
            raise RuleExecutionError("RULE manifest requires a list of all conditions")

        for condition in conditions:
            if not isinstance(condition, dict) or "field" not in condition or "equals" not in condition:
                raise RuleExecutionError("RULE conditions require field and equals")

        matched = all(payload.get(condition["field"]) == condition["equals"] for condition in conditions)
        return {"matched": matched, "result": rule.get("result") if matched else None}
