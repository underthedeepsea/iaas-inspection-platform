import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it } from 'vitest'
import { InspectionFacts } from './InspectionFacts'
import type { InspectionFactReport } from '../../api/inspectionFacts'

import { syntheticHostDiagnosticReport } from './fixtures/hostDiagnosticReport.synthetic'

function view(report: InspectionFactReport) { return render(<MemoryRouter><InspectionFacts report={report} environmentId="synthetic-env-a" /></MemoryRouter>) }

it('shows the synthetic historical missing coverage and insufficient history together without changing evidence', () => {
 const original=structuredClone(syntheticHostDiagnosticReport);view(syntheticHostDiagnosticReport)
 expect(screen.getByText('31.25%')).toHaveAttribute('title','host/cpu_busy_ratio: 0.3125 ratio')
 expect(screen.getAllByText(/采集不完整、历史不足/).length).toBeGreaterThanOrEqual(2)
 expect(screen.getByText(/已有 0 个样本；原规则至少8点/)).toBeVisible()
 expect(screen.getByText(/已有 1 个样本；原规则至少6点/)).toBeVisible()
 expect(screen.getByText(/磁盘：采集不完整/)).toBeVisible()
 expect(screen.getByText(/文件系统：采集不完整/)).toBeVisible()
 const raw=screen.getByText(/UNKNOWN · CODE/)
 expect(raw.closest('details')).not.toHaveAttribute('open')
 const source=screen.getAllByText(/synthetic-macos-observation-only/)[0]
 expect(source.closest('details')).not.toHaveAttribute('open')
 expect(screen.getByText(/历史Mac观测不作为Linux服务器验收/).closest('details')).not.toHaveAttribute('open')
 expect(syntheticHostDiagnosticReport).toEqual(original)
})
it('keeps confirmed abnormalities and risks ahead of missing inputs', () => {
 const report=structuredClone(syntheticHostDiagnosticReport);report.checks[0].status='FAIL'
 report.checks[0].host_diagnostics!.items[0].status='WARNING'
 report.checks[0].risks=[{id:'risk',title:'已确认风险',status:'NEW',severity:'P1',state_source:'CURRENT'}]
 view(report)
 expect(screen.getAllByText('发现异常').length).toBeGreaterThan(0)
 expect(screen.getByText(/CPU条件漂移 · 发现异常/)).toBeVisible()
 expect(screen.getByText(/已确认风险/)).toHaveAttribute('href','/risks/risk?environment=synthetic-env-a')
 expect(screen.getByText(/磁盘：采集不完整/)).toBeVisible()
})
