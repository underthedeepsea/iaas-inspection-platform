import math
from collections import defaultdict

from . import CheckResultSpec


def check_llm_queue_backlog(*, reader, assets, config):
    threshold = float(config.get('threshold', 10))
    count = int(config.get('consecutive_points', 3))
    if count < 1 or not math.isfinite(threshold) or threshold < 0:
        raise ValueError('Invalid queue configuration')
    expected = {'threshold': threshold, 'consecutive_points': count}
    applicable = [asset for asset in assets if asset.asset_type == 'LLM_INSTANCE']
    points_by_asset = defaultdict(list)
    if applicable:
        for point in reader.metrics(config.get('metric', 'queue_depth'), asset_ids=[asset.pk for asset in applicable]):
            points_by_asset[point.asset_id].append(point)
    results = []
    for asset in assets:
        if asset.asset_type != 'LLM_INSTANCE':
            results.append(CheckResultSpec(asset, 'NOT_APPLICABLE', '仅适用于 LLM 实例', expected_value=expected))
            continue
        try:
            points = sorted(points_by_asset[asset.pk], key=lambda p: (p.ts, p.id))
            values = [float(p.value) for p in points]
            if not all(math.isfinite(v) and v >= 0 for v in values):
                raise ValueError('Invalid queue sample')
        except (TypeError, ValueError, OverflowError):
            results.append(CheckResultSpec(asset, 'ERROR', 'Queue 样本格式错误', expected_value=expected, evidence={'error_code': 'INVALID_SAMPLE'}))
            continue
        status = 'UNKNOWN' if len(points) < count else 'FAIL' if all(v > threshold for v in values[-count:]) else 'PASS'
        results.append(CheckResultSpec(asset, status, f'不足 {count} 点，无法判断' if status == 'UNKNOWN' else f'最近 {count} 点连续超限' if status == 'FAIL' else f'最近 {count} 点未连续超限', {'last_values': values[-count:], 'sample_count': len(points)}, expected, {'metric': config.get('metric', 'queue_depth'), 'samples': [{'id':p.id, 'ts':p.ts.isoformat(), 'value':p.value} for p in points[-count:]]}))
    return results
