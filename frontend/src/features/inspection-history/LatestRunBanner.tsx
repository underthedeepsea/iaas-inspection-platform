import { Link } from 'react-router-dom'
import { useInspectionSessionStore } from '../../stores/inspectionSessionStore'

export function LatestRunBanner({environmentId}: {environmentId: string}) {
  const run = useInspectionSessionStore(state => state.lastCompleted)
  if (!run || run.environmentId !== environmentId) return null
  const path = `/inspection-runs/${run.runId}?environment=${environmentId}`
  return <aside className="latest-run-banner" aria-label="最近完成的巡检"><span className="latest-run-check" aria-hidden="true">✓</span><div><strong>{run.status === 'PARTIAL' ? '你刚刚完成了一次巡检，部分检查需要关注' : '你刚刚完成了一次巡检'}</strong><small>RUN {run.runId.slice(0, 8)} · {run.resourceTypes.map(code => code === 'CONTROL_PLANE' ? '控制面' : code === 'LLM_RUNTIME' ? 'LLM 运行时' : code).join(' + ')}</small></div><Link to={path}>查看本次结果 →</Link><Link to={`${path}#ai-explanation`}>AI 解读</Link></aside>
}
