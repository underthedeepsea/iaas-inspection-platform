/// <reference types="vite/client" />
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import css from './CheckResultsTable.css?raw'
import { CheckResultsTable } from './CheckResultsTable'
import { revealReportTarget } from '../../pages/InspectionRunResult/InspectionRunResultPage'
import type { CheckResult } from '../../api/resources'

it('keeps unbroken and deeply nested raw evidence intact, associated, and toggleable', () => {
 const long='unbroken_'+ 'abcdef0123456789'.repeat(160)
 const evidence={snapshot:{identity:{asset:'asset-long',raw:long},samples:[{level:{next:{value:long,keep:false}}}]},reason_code:'SNAPSHOT_STALE'}
 const row:CheckResult={id:'raw-long',inspection_item_code:'hardware.host_health',inspection_item_name:'主机',asset_id:'asset-long',asset_name:'host-long',status:'UNKNOWN',summary:'硬件快照已超过有效时限',observed_value:{current:long},expected_value:{nested:{rule:long}},evidence,checked_at:'2026-10-28T15:16:13Z'}
 const {container}=render(<details><summary>原始检查</summary><CheckResultsTable results={[row]}/></details>)
 const target=container.querySelector('#check-raw-long')! as HTMLElement
 target.scrollIntoView=vi.fn()
 revealReportTarget('#check-raw-long')
 expect(target.scrollIntoView).toHaveBeenCalledOnce()
 expect(container.querySelector('details')).toHaveAttribute('open')
 const details=target.querySelector('.check-evidence')! as HTMLDetailsElement
 expect(details.open).toBe(false)
 fireEvent.click(screen.getByText('展开证据'))
 expect(details.open).toBe(true)
 const pre=details.querySelector('pre')!
 expect(pre.textContent).toBe(JSON.stringify(evidence,null,2))
 expect(JSON.parse(pre.textContent!)).toEqual(evidence)
 expect(details.parentElement).toHaveAttribute('data-column','证据与时间')
 expect(details).toHaveTextContent('Asset：asset-long')
 expect(screen.getByText('硬件快照已超过有效时限')).toBeVisible()
 fireEvent.click(screen.getByText('展开证据'))
 expect(details.open).toBe(false)
 expect(pre.textContent).toContain(long)
})
it('scopes width and wrapping contracts to this table with a full-row evidence area', () => {
 expect(css).toContain('table-layout: fixed')
 expect(css).toContain('min-width: 0')
 expect(css).toContain('white-space: normal')
 expect(css).toContain('white-space: pre-wrap')
 expect(css).toContain('overflow-wrap: anywhere')
 expect(css).toContain('@container (max-width: 1100px)')
 expect(css).toContain('grid-column: 1 / -1')
 expect(css).not.toMatch(/text-overflow|line-clamp|display:\s*none/)
})
