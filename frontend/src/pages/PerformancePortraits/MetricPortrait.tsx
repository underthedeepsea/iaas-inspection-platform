import { useState } from 'react'
import type { ProfileMetric, PortraitPoint } from '../../api/performanceProfile'
import { display, difference, metricTime, missingReason } from './portraitModel'
function pointText(point:PortraitPoint,unit:string) {
  return `${point.is_current?'当前有效观测':'历史观测'} · ${display(point.value,unit)} · ${point.value_kind==='WINDOW_STATISTIC'?`统计窗口 ${point.window_start} → ${point.window_end}`:`采集 ${point.collected_at??point.at}`} · 来源 ${point.source??'未记录'} · 同钟点参考上下界未提供`
}
function referenceText(point:PortraitPoint,metric:ProfileMetric) {
  return point.is_current&&metric.history.n>=2?`当前点可比条件历史中位数 ${display(metric.history.median,metric.unit)}，观察范围 ${display(metric.history.min,metric.unit)} — ${display(metric.history.max,metric.unit)}；非同钟点常态`:'该历史点当时的参考上下界未保留，不回填当前范围'
}
export function MetricPortrait({metric}:{metric:ProfileMetric}) {
  const [selected,setSelected]=useState<string|null>(null)
  const points=(metric.series??[]).filter(point=>point.at&&point.value!=null&&Number.isFinite(point.value))
  const chosen=points.find(p=>p.snapshot_id===selected)??points[points.length-1]
  const times=points.map(p=>Date.parse(p.at!)), values=points.map(p=>p.value!)
  const tmin=Math.min(...times),tmax=Math.max(...times),vmin=Math.min(...values),vmax=Math.max(...values)
  const x=(p:PortraitPoint)=>40+(Date.parse(p.at!)-tmin)/(tmax-tmin||1)*620
  const y=(p:PortraitPoint)=>155-(p.value!-vmin)/(vmax-vmin||1)*115
  return <article className="portrait-metric" aria-label={metric.label}>
    <header><div><h3>{metric.label}</h3><small>{metric.unit} · {metric.value_kind==='WINDOW_STATISTIC'?'原窗口统计':metric.value_kind==='POINT_AGGREGATE'?'参与点聚合':'真实采集点'}</small></div><strong>{display(metric.current,metric.unit)}</strong></header>
    <p className="portrait-muted">{metricTime(metric)}</p><p>{missingReason(metric)}</p>
    {metric.current==null&&metric.latest_observed!=null?<p>最近历史观测 <b>{display(metric.latest_observed,metric.unit)}</b>（不作为当前值）</p>:null}
    <div className="portrait-statline"><span>历史中位数 <b>{display(metric.history.median,metric.unit)}</b></span><span>观察范围 <b>{display(metric.history.min,metric.unit)} — {display(metric.history.max,metric.unit)}</b></span><span>当前偏离 <b>{difference(metric)}</b></span></div>
    {metric.current!=null&&metric.history.min!=null&&metric.history.max!=null?<p>{metric.current<metric.history.min?'当前低于':metric.current>metric.history.max?'当前高于':'当前位于'}同已知条件历史观察范围；这是描述差异，非同钟点常态或故障判定。</p>:null}
    {points.length?<><svg className="portrait-chart" viewBox="0 0 700 200" role="group" aria-label={`${metric.label}真实离散观测`}><line x1="40" x2="660" y1="160" y2="160" stroke="#ddd"/><text x="8" y="25">{display(vmax,metric.unit)}</text><text x="8" y="185">{display(vmin,metric.unit)}</text>{points.map(p=><circle key={p.snapshot_id} cx={x(p)} cy={y(p)} r={chosen?.snapshot_id===p.snapshot_id?6:4} fill={p.is_current?'#bc5d28':'#8b949c'} tabIndex={0} role="button" aria-label={pointText(p,metric.unit)+' · '+referenceText(p,metric)} onFocus={()=>setSelected(p.snapshot_id)} onMouseEnter={()=>setSelected(p.snapshot_id)} onClick={()=>setSelected(p.snapshot_id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setSelected(p.snapshot_id)}}}><title>{pointText(p,metric.unit)+' · '+referenceText(p,metric)}</title></circle>)}</svg><p className="portrait-time-axis"><time>{points[0].at}</time><time>{points[points.length-1].at}</time></p><label className="portrait-point-picker">查看观测点 <select value={chosen?.snapshot_id??''} onChange={e=>setSelected(e.target.value)}>{points.map(p=><option key={p.snapshot_id} value={p.snapshot_id}>{p.at} · {display(p.value,metric.unit)}</option>)}</select></label><p className="portrait-point-detail" role="status">{chosen?pointText(chosen,metric.unit)+' · '+referenceText(chosen,metric):''}</p></>:<div className="portrait-chart-empty">没有可绘制的可靠观测点。{metric.series_note??'历史点尚未返回。'}</div>}
    <p className="portrait-muted">仅画真实离散点；缺测或连续性未知处不连线。曲线截止最后真实观测，不延伸到现在。{metric.series?.some(p=>p.value==null)?'本窗口存在缺测点。':''}</p>
    <p className="portrait-muted">历史 n={metric.history.n} · {metric.history.start??'—'} 至 {metric.history.end??'—'}；只描述{metric.history.n>=2?'已知条件':'不足的历史'}，不是完整14天覆盖。{metric.coverage?` 当前覆盖 ${metric.coverage.covered}/${metric.coverage.total} 节点。`:''}</p>
    {metric.series_truncated?<p role="status">原始系列达到1000点上限，只显示最近返回点。</p>:null}
    <details><summary>历史参考能力与原始字段</summary><p>{metric.series_note??'未保留逐点同钟点上下界，历史带与连续偏离片段暂不可用。'} 14天min/max只放在当前摘要旁，不回填到历史点。</p><p>未记录比较条件：{metric.missing_context.join('、')||'无额外记录'}</p><pre>{JSON.stringify({key:metric.key,state:metric.state,value_kind:metric.value_kind},null,2)}</pre></details>
  </article>
}
