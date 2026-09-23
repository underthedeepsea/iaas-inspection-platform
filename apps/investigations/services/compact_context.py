"""Small, fact-preserving input shared by the two explanation entry points."""

import json
import re


MAX_CHECKS = 8
MAX_BYTES = 8000
_PRIORITY = {"FAIL": 0, "ERROR": 1, "UNKNOWN": 2, "PASS": 3, "NOT_APPLICABLE": 4}
_UNTRUSTED_DIRECTIVE = re.compile(r"(?i)(?:忽略.{0,12}指令|调用.{0,8}工具|修改.{0,8}风险|ignore.{0,20}instructions|system\s*prompt)")
_CITATION = re.compile(r"(?i)\b(?:check|risk|asset|run)-[a-z0-9_-]+\b|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_UNSUPPORTED_RUN_COUNT = re.compile(r"(?:仅|只|只有|仅有).{0,8}(?:一|1)次(?:巡检|运行)(?:记录)?|(?:仅|只|只有|仅有).{0,8}(?:一|1)(?:条|次|个)(?:性能)?快照|第(?:一|1)次巡检")
_UNSUPPORTED_TREND_GAP = re.compile(r"(?:无|没有|缺少|缺乏|未提供)[^。；;]{0,10}(?:历史|前次|趋势)[^。；;]{0,20}(?:趋势|变化趋势)")


def _text(value, limit):
    cleaned = str(value or "")[:limit]
    directive = _UNTRUSTED_DIRECTIVE.search(cleaned)
    if directive:
        cleaned = cleaned[:directive.start()].rstrip(" 。；，")
    return cleaned


def validate_explanation_answer(answer, context):
    if not isinstance(answer, str) or not answer.strip() or _UNTRUSTED_DIRECTIVE.search(answer):
        raise ValueError("explanation repeated an untrusted instruction")
    if context.get("previous_run") is None and re.search(r"首次(?:执行|巡检|运行)", answer):
        raise ValueError("explanation inferred an unsupported first run")
    if _UNSUPPORTED_RUN_COUNT.search(answer):
        raise ValueError("explanation inferred an unsupported history count")
    trend_ready = any(
        (row.get("facts") or {}).get("trend", {}).get("status") in {"WATCH", "DEGRADING", "STABLE"}
        for row in context.get("check_results") or []
    )
    if trend_ready and _UNSUPPORTED_TREND_GAP.search(answer):
        raise ValueError("explanation denied supplied trend evidence")
    known = {str(context.get("inspection_run_id") or "")}
    for row in context.get("check_results") or []:
        known.update((str(row.get("id") or ""), str(row.get("asset_id") or "")))
    for cited in _CITATION.findall(answer):
        if cited not in known:
            raise ValueError("explanation cited an unknown identifier")


def _facts(value):
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in (
        "code", "metric", "current", "value", "unit", "threshold", "boundary",
        "baseline", "baseline_median", "change_ratio", "window_start", "window_end",
        "snapshot_id", "quality", "status",
    ) if key in value}


def _check(row):
    evidence = row.get("evidence")
    if isinstance(evidence, dict):
        evaluation = evidence.get("evaluation")
        if not isinstance(evaluation, dict):
            evaluation = {}
        reasons = evaluation.get("reasons") or evidence.get("reasons") or []
        if not isinstance(reasons, list):
            reasons = []
        facts = {**_facts(evidence), **_facts(evaluation)}
        dynamic = evaluation.get("dynamic")
        if isinstance(dynamic, dict):
            facts["dynamic"] = {key: dynamic[key] for key in ("status", "baseline_state") if key in dynamic}
            quality_reasons = [item.get("quality_reason") for item in (dynamic.get("metrics") or {}).values() if isinstance(item, dict)] if isinstance(dynamic.get("metrics"), dict) else []
            if quality_reasons:
                facts["dynamic"]["quality_reasons"] = sorted(set(reason for reason in quality_reasons if reason))[:2]
        trend = evaluation.get("trend")
        if isinstance(trend, dict):
            facts["trend"] = {key: trend[key] for key in ("status",) if key in trend}
    else:
        reasons, facts = [], {}
    return {
        "id": row.get("id"), "check": row.get("check") or row.get("inspection_item_code"),
        "asset_id": row.get("asset_id"), "status": row.get("status"),
        "summary": _text(row.get("summary"), 300),
        "observed": row.get("observed", row.get("observed_value")),
        "expected": row.get("expected", row.get("expected_value")),
        "facts": facts,
        "reasons": [_facts(reason) for reason in reasons[:2] if isinstance(reason, dict)],
    }


def build_compact_explanation_context(context, *, question=""):
    rows = context.get("check_results") or []
    rows = sorted(rows, key=lambda row: (_PRIORITY.get(row.get("status"), 5), str(row.get("id", ""))))
    total = (context.get("summary") or {}).get("check_count", len(rows))
    if not isinstance(total, int) or total < len(rows):
        total = len(rows)
    counts = (context.get("summary") or {}).get("status_counts")
    if not isinstance(counts, dict):
        flat = context.get("summary") or {}
        if all(f"{status.lower()}_count" in flat for status in _PRIORITY):
            counts = {status: flat[f"{status.lower()}_count"] for status in _PRIORITY}
        elif total == len(rows):
            counts = {status: sum(row.get("status") == status for row in rows) for status in _PRIORITY}
        else:
            counts = {}
    result = {
        "inspection_run_id": context.get("inspection_run_id") or (context.get("run") or {}).get("id"),
        "resource_type": context.get("resource_type"),
        "question": _text(question, 300),
        "summary": {"check_count": total, "status_counts": counts, "status_counts_complete": bool(counts)},
        "check_results": [_check(row) for row in rows[:MAX_CHECKS]],
        "previous_run": context.get("previous_run"),
        "comparison_note": "缺少前次巡检摘要，无法比较；历史运行次数未知。" if context.get("previous_run") is None else "仅按提供的前次摘要比较",
        "omitted_count": max(0, total - min(len(rows), MAX_CHECKS)),
        "truncated": total > MAX_CHECKS or len(question) > 300,
    }
    if result["previous_run"] is not None:
        prior = result["previous_run"]
        result["previous_run"] = {key: prior.get(key) for key in ("run", "summary") if key in prior} if isinstance(prior, dict) else None
    def size():
        return len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    while size() > MAX_BYTES and result["check_results"]:
        result["check_results"].pop()
        result["omitted_count"] += 1
        result["truncated"] = True
    if size() > MAX_BYTES:
        result["previous_run"] = None
    return result
