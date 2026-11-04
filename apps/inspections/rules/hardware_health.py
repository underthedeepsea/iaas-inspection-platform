from datetime import datetime
from . import CheckResultSpec
from apps.hardware_health.evaluator import PLUGIN
from apps.hardware_health.host_policy import HOST_PLUGIN, freshness_seconds


def check_hardware_health(*,reader,assets,config):
    results=[]
    for asset in assets:
        frozen=reader.hardware_input(asset.pk)
        valid=False
        reason='NO_DATA';field='snapshot';details={}
        if frozen:
            try:
                end=datetime.fromisoformat(frozen['window_end']);as_of=datetime.fromisoformat(frozen['frozen_at'])
                created=datetime.fromisoformat(frozen['created_at']);evaluation=frozen['evaluation']
                details={key:frozen[key] for key in ('window_end','frozen_at','created_at')}
                limit=freshness_seconds(evaluation);details['freshness_seconds']=limit
                if end.tzinfo is None or as_of.tzinfo is None or created.tzinfo is None:
                    reason='TIMEZONE_MISSING';field='window_end/frozen_at/created_at'
                elif (as_of-end).total_seconds()<0:
                    reason='FUTURE_WINDOW';field='window_end'
                elif (as_of-end).total_seconds()>limit:
                    reason='SNAPSHOT_STALE';field='window_end';details['age_seconds']=(as_of-end).total_seconds()
                elif created>as_of:
                    reason='CREATED_AFTER_FREEZE';field='created_at'
                elif frozen['asset_id']!=str(asset.pk) or frozen['environment_id']!=str(asset.environment_id):
                    reason='IDENTITY_MISMATCH';field='asset_id/environment_id'
                    details.update(asset_id=frozen['asset_id'],environment_id=frozen['environment_id'],expected_asset_id=str(asset.pk),expected_environment_id=str(asset.environment_id))
                elif evaluation['plugin'] not in (PLUGIN,HOST_PLUGIN):
                    reason='PLUGIN_VERSION_MISMATCH';field='evaluation.plugin';details['recorded_plugin']=evaluation['plugin']
                elif evaluation['input']['snapshot_id']!=frozen['snapshot_id']:
                    reason='SNAPSHOT_MISMATCH';field='evaluation.input.snapshot_id'
                    details.update(snapshot_id=frozen['snapshot_id'],evaluation_snapshot_id=evaluation['input']['snapshot_id'])
                else: valid=True
            except (KeyError,ValueError,TypeError,AttributeError) as exc:
                reason='MALFORMED_INPUT';field=str(exc.args[0]) if isinstance(exc,KeyError) else 'time/evaluation'
        if not valid:
            descriptions={'NO_DATA':'没有收到本对象硬件快照','SNAPSHOT_STALE':'硬件快照已超过有效时限','IDENTITY_MISMATCH':'快照对象或环境身份不符','PLUGIN_VERSION_MISMATCH':'快照插件版本不受当前规则支持','SNAPSHOT_MISMATCH':'冻结结果与快照编号不符','TIMEZONE_MISSING':'快照时间未记录时区','FUTURE_WINDOW':'快照窗口晚于冻结时间','CREATED_AFTER_FREEZE':'快照创建时间晚于冻结时间','MALFORMED_INPUT':'快照必需字段或时间格式无效'}
            results.append(CheckResultSpec(asset,'UNKNOWN',descriptions[reason],evidence={'error_code':'INVALID_HARDWARE_INPUT','reason_code':reason,'field':field,**details,'impact':'本项无法形成有效健康结论；不改变其他检查的已确认结果。','next_step':'核对对应来源、对象映射、时间及插件版本，修复后通过受控新巡检复查。'}));continue
        status=evaluation['status'];failure=status in {'WARNING','CRITICAL'}
        summary='硬件存在已确认异常' if failure else '硬件基础检查通过；高级诊断覆盖见证据' if status=='NORMAL' else '硬件数据不足或异常待确认'
        results.append(CheckResultSpec(asset,'FAIL' if failure else 'PASS' if status=='NORMAL' else 'UNKNOWN',summary,
            observed_value={'status':status,'snapshot_id':frozen['snapshot_id']},
            expected_value={'source':'gpu-host-health','policy_version':evaluation['plugin']['version']},
            evidence={'source_type':'HARDWARE_SNAPSHOT','snapshot_id':frozen['snapshot_id'],
                      'window_start':frozen['window_start'],'window_end':frozen['window_end'],
                      'evaluation':evaluation,'components':{k:v['identity'] for k,v in frozen['payload']['metrics'].items()},
                      'hardware_reverification':frozen['payload'].get('hardware_reverification')},severity='P1' if status=='CRITICAL' else 'P2' if failure else None))
    return results
