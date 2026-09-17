import { useQuery } from '@tanstack/react-query'
import { getInspectionRunResult } from '../../api/inspectionRunResult'
import type { TerminalStatus } from '../../stores/inspectionSessionStore'

export function InspectionCompletion({runId, environmentId, status, resourceTypes}: {runId:string; environmentId:string; status:TerminalStatus; resourceTypes:string[]}) {
  const query = useQuery({queryKey:['inspection-result',environmentId,runId],queryFn:() => getInspectionRunResult(runId,environmentId)})
  const detail = query.data
  return <section className={`inspection-completion${status === 'FAILED' ? ' is-failed' : ''}`} aria-label="巡检完成摘要">
    <span className="completion-mark" aria-hidden="true">{status === 'FAILED' ? '!' : '✓'}</span>
    <h3>{status === 'PARTIAL' ? '本次巡检部分完成' : status === 'FAILED' ? '巡检失败' : '本次巡检已完成'}</h3>
    <p className="mono run-identity">{runId}</p>
    <div className="completion-scope">{resourceTypes.map(code => <span key={code}>{code === 'CONTROL_PLANE' ? '控制面' : code === 'LLM_RUNTIME' ? 'LLM 运行时' : code}</span>)}</div>
    {detail ? <div className="completion-stats"><div><strong>{detail.code_plugins.length}</strong><span>代码插件</span></div><div><strong className="text-fail">{detail.summary.fail_count}</strong><span>FAIL</span></div><div><strong className="text-pass">{detail.summary.pass_count}</strong><span>PASS</span></div><div><strong>{detail.summary.risk_count}</strong><span>关联风险</span></div></div> : <p role="status">{query.isError ? '摘要暂时无法加载，可进入结果页重试。' : '正在读取本次巡检摘要…'}</p>}
    {status === 'FAILED' ? <p>{detail?.run.error_message || '请查看失败详情，检查执行记录与证据。'}</p> : <p>先查看 CODE 巡检结果，需要了解原因时再使用 AI 解读。</p>}
  </section>
}
