import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it } from 'vitest'
import { InspectionFacts } from './InspectionFacts'
import { resultLabel, reportLabel } from './resultLabels'
import type { InspectionFactReport } from '../../api/inspectionFacts'
const row={id:'controlled',check:'hardware.host_health',check_name:'受控展示检查',asset_id:'controlled',asset_name:'受控资产',status:'UNKNOWN',summary:'受控展示数据，非真实Run',quality:{state:'INCOMPLETE'},evidence_gaps:['INCOMPLETE','DYNAMIC_BASELINE_NOT_READY'],measurements:[],risks:[]}
const report:InspectionFactReport={source:'CODE',inspection_run_id:'controlled-display-only',check_count:1,status_counts:{UNKNOWN:1},checks:[row],omitted_count:0,risk_state_note:'受控展示数据，非真实Run'}
it('labels only recorded reasons and preserves FAIL and ERROR priority',()=>{
 expect(resultLabel(row)).toBe('采集不完整、历史不足')
 expect(resultLabel({...row,status:'FAIL'})).toBe('发现异常')
 expect(resultLabel({...row,status:'ERROR'})).toBe('执行失败')
 expect(resultLabel({status:'UNKNOWN'})).toBe('无法判断')
 expect(resultLabel({status:'UNKNOWN',evidence:{reason_code:'NO_DATA'}})).toBe('未采集')
 expect(resultLabel({status:'UNKNOWN',quality:{state:'STALE'}})).toBe('数据过期')
 expect(reportLabel([{status:'UNKNOWN'}, {status:'FAIL'}])).toMatch(/^发现异常/)
})
it('keeps raw state behind expandable technical details and all abnormal measurements visible',()=>{
 const measured={...report,checks:[{...row,status:'FAIL',measurements:Array.from({length:6},(_,i)=>({layer:'HARDWARE',code:'ECC_DBE_NEW',current:i+1,value_semantics:'EVENT' as const}))}]}
 render(<MemoryRouter><InspectionFacts report={measured} environmentId="controlled" /></MemoryRouter>)
 expect(screen.getByText('6')).toBeVisible()
 const details=screen.getByText('原始状态、来源与验收边界').closest('details')!
 expect(details).not.toHaveAttribute('open')
 expect(details.textContent).toContain('FAIL')
 fireEvent.click(screen.getByText('原始状态、来源与验收边界'))
 details.open=true
 expect(details).toHaveAttribute('open')
})
