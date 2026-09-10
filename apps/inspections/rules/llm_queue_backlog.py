import math

from . import CheckResultSpec


def check_llm_queue_backlog(*, reader, assets, config):
    threshold = float(config.get('threshold', 10))
    count = int(config.get('consecutive_points', 3))
    if count < 1 or not math.isfinite(threshold) or threshold < 0:
        raise ValueError('Invalid queue configuration')
    expected = {'threshold': threshold, 'consecutive_points': count}
    results = []
    for asset in assets:
        if asset.asset_type != 'LLM_INSTANCE':
            results.append(CheckResultSpec(asset, 'NOT_APPLICABLE', '仅适用于 LLM 实例', expected_value=expected))
            continue
        points = sorted(reader.metrics(config.get('metric', 'queue_depth'), asset_ids=[asset.pk]), key=lambda p: (p.ts, p.id))
        values = [float(p.value) for p in points]
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError('Invalid queue sample')
        status = 'UNKNOWN' if len(points) < count else 'FAIL' if all(v > threshold for v in values[-count:]) else 'PASS'
        results.append(CheckResultSpec(asset, status, '队列采样不足' if status == 'UNKNOWN' else '队列连续积压' if status == 'FAIL' else '队列未持续积压', {'last_values': values[-count:], 'sample_count': len(points)}, expected, {'metric': config.get('metric', 'queue_depth'), 'samples': [{'id':p.id, 'ts':p.ts.isoformat(), 'value':p.value} for p in points[-count:]]}))
    return results
