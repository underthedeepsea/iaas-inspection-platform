"""The sole registered owner of inference performance evaluation."""

from datetime import datetime

from django.utils import timezone

from . import CheckResultSpec
from apps.inference_performance.services.evaluator import evaluate_snapshot


def _map_status(evaluation):
    quality = evaluation.get('quality') or {}
    if quality.get('state') == 'IDLE':
        return 'UNKNOWN', None, '引擎空闲，无法确认性能状态'
    status = evaluation.get('status')
    if status == 'CRITICAL':
        return 'FAIL', 'P1', '推理性能达到严重阈值'
    if status == 'WARNING':
        return 'FAIL', 'P2', '推理性能超过预警阈值'
    if quality.get('pending_confirmation'):
        return 'UNKNOWN', None, '异常值尚待持续确认'
    if status == 'NORMAL':
        return 'PASS', None, '推理性能符合当前策略'
    return 'UNKNOWN', None, '暂无有效推理性能评估'


def _positive_age(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError('max_age_seconds must be a positive integer')
    return value


def _frozen_valid(asset, frozen, configured_age):
    evaluation = frozen.get('evaluation') or {}
    plugin = evaluation.get('plugin') or {}
    identity = frozen.get('identity') or {}
    if plugin.get('id') != 'inference-performance' or plugin.get('version') != '1.0.0':
        return False
    if str(frozen.get('snapshot_id')) != str((evaluation.get('input') or {}).get('snapshot_id')):
        return False
    if identity and (
        identity.get('asset_id') not in (None, str(asset.pk))
        or identity.get('environment_id') not in (None, str(asset.environment_id))
    ):
        return False
    labels = asset.labels or {}
    if any(frozen.get(field) not in (None, labels.get(field)) for field in ('engine_id', 'engine_type', 'model_name')):
        return False
    frozen_at = frozen.get('frozen_at')
    window_end = frozen.get('window_end')
    if not frozen_at or not window_end:
        return False
    max_age = _positive_age(((evaluation.get('resolved_policy') or {}).get('quality') or {}).get('max_age_seconds', configured_age))
    try:
        as_of = datetime.fromisoformat(frozen_at) if isinstance(frozen_at, str) else frozen_at
        end = datetime.fromisoformat(window_end) if isinstance(window_end, str) else window_end
        if timezone.is_naive(as_of) or timezone.is_naive(end) or end > as_of:
            return False
        created_at = frozen.get('created_at')
        if created_at:
            created = datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at
            if timezone.is_naive(created) or created > as_of:
                return False
        return 0 <= (as_of - end).total_seconds() <= max_age
    except (TypeError, ValueError):
        return False


def check_inference_performance(*, reader, assets, config):
    results = []
    for asset in assets:
        try:
            configured_age = _positive_age(config.get('max_age_seconds', 300))
        except (TypeError, ValueError) as error:
            results.append(CheckResultSpec(asset, 'ERROR', '推理性能配置无效', evidence={'error_code': type(error).__name__}))
            continue
        if asset.asset_type != 'LLM_INSTANCE':
            results.append(CheckResultSpec(asset, 'NOT_APPLICABLE', '仅适用于 LLM 实例'))
            continue
        item = reader.performance_input(asset.pk)
        if item is None:
            results.append(CheckResultSpec(asset, 'UNKNOWN', '没有推理性能快照', evidence={'error_code': 'NO_DATA'}))
            continue
        try:
            if item.mode == 'COMPUTE':
                evaluation = evaluate_snapshot(item.snapshot)
                snapshot_id = str(item.snapshot.pk)
                window_start = item.snapshot.window_start.isoformat()
                window_end = item.snapshot.window_end.isoformat()
            else:
                frozen = item.frozen or {}
                if not _frozen_valid(asset, frozen, configured_age):
                    results.append(CheckResultSpec(asset, 'UNKNOWN', '冻结结果版本、身份或时效无效', evidence={'error_code': 'INVALID_FROZEN_RESULT'}))
                    continue
                evaluation = frozen['evaluation']
                snapshot_id = frozen['snapshot_id']
                window_start = frozen.get('window_start')
                window_end = frozen.get('window_end')
            status, severity, summary = _map_status(evaluation)
            results.append(CheckResultSpec(
                asset, status, summary,
                observed_value={'status': evaluation.get('status'), 'snapshot_id': snapshot_id},
                expected_value={'policy_source': evaluation.get('policy_source'), 'resolved_policy': evaluation.get('resolved_policy')},
                evidence={'snapshot_id': snapshot_id, 'window_start': window_start, 'window_end': window_end,
                          'quality': evaluation.get('quality', {}),
                          'pending_confirmation': (evaluation.get('quality') or {}).get('pending_confirmation', False),
                          'evaluation': evaluation}, severity=severity,
            ))
        except Exception as error:
            results.append(CheckResultSpec(asset, 'ERROR', '推理性能评估失败', evidence={'error_code': type(error).__name__}))
    return results
