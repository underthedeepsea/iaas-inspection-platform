from datetime import datetime
from . import CheckResultSpec
from apps.hardware_health.evaluator import PLUGIN


def check_hardware_health(*,reader,assets,config):
    results=[]
    for asset in assets:
        frozen=reader.hardware_input(asset.pk)
        valid=False
        if frozen:
            try:
                end=datetime.fromisoformat(frozen['window_end']);as_of=datetime.fromisoformat(frozen['frozen_at'])
                created=datetime.fromisoformat(frozen['created_at'])
                evaluation=frozen['evaluation']
                valid=(end.tzinfo is not None and as_of.tzinfo is not None and created.tzinfo is not None
                    and 0<=(as_of-end).total_seconds()<=300 and created<=as_of
                    and frozen['asset_id']==str(asset.pk) and frozen['environment_id']==str(asset.environment_id)
                    and evaluation['plugin']==PLUGIN and evaluation['input']['snapshot_id']==frozen['snapshot_id'])
            except (KeyError,ValueError,TypeError): pass
        if not valid:
            results.append(CheckResultSpec(asset,'UNKNOWN','硬件快照缺失、过期或身份无效',evidence={'error_code':'INVALID_HARDWARE_INPUT'}));continue
        status=evaluation['status'];failure=status in {'WARNING','CRITICAL'}
        summary='硬件存在已确认异常' if failure else '硬件基础检查通过；高级诊断覆盖见证据' if status=='NORMAL' else '硬件数据不足或异常待确认'
        results.append(CheckResultSpec(asset,'FAIL' if failure else 'PASS' if status=='NORMAL' else 'UNKNOWN',summary,
            observed_value={'status':status,'snapshot_id':frozen['snapshot_id']},
            expected_value={'source':'gpu-host-health','policy_version':'1.0.0'},
            evidence={'source_type':'HARDWARE_SNAPSHOT','snapshot_id':frozen['snapshot_id'],
                      'window_start':frozen['window_start'],'window_end':frozen['window_end'],
                      'evaluation':evaluation,'components':{k:v['identity'] for k,v in frozen['payload']['metrics'].items()},
                      'hardware_reverification':frozen['payload'].get('hardware_reverification')},severity='P1' if status=='CRITICAL' else 'P2' if failure else None))
    return results
