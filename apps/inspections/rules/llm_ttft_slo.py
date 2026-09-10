import math

from . import CheckResultSpec


def check_llm_ttft_slo(*, reader, assets, config):
    threshold = float(config.get('threshold_ms', 180))
    minimum = int(config.get('min_samples', 3))
    if minimum < 1 or not math.isfinite(threshold) or threshold < 0 or config.get('percentile', 95) != 95:
        raise ValueError('Invalid TTFT configuration')
    expected = {'threshold_ms': threshold, 'min_samples': minimum, 'percentile': 95, 'algorithm': 'nearest_rank'}
    results = []
    for asset in assets:
        if asset.asset_type != 'LLM_INSTANCE':
            results.append(CheckResultSpec(asset, 'NOT_APPLICABLE', '仅适用于 LLM 实例', expected_value=expected))
            continue
        points = list(reader.metrics(config.get('metric', 'ttft_ms'), asset_ids=[asset.pk]))
        values = [float(p.value) for p in points]
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError('Invalid TTFT sample')
        p95 = sorted(values)[math.ceil(.95*len(values))-1] if len(values) >= minimum else None
        status = 'UNKNOWN' if p95 is None else 'FAIL' if p95 > threshold else 'PASS'
        results.append(CheckResultSpec(asset, status, 'TTFT 样本不足' if p95 is None else 'TTFT P95 超过阈值' if status == 'FAIL' else 'TTFT P95 满足阈值', {'p95_ms': p95, 'sample_count': len(values)}, expected, {'metric': config.get('metric', 'ttft_ms'), 'samples': [{'id':p.id, 'ts':p.ts.isoformat(), 'value':p.value} for p in points], 'window_start': points[0].ts.isoformat() if points else None, 'window_end': points[-1].ts.isoformat() if points else None}))
    return results
