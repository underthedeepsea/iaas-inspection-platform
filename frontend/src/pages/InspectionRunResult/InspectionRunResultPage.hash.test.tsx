import {expect,it,vi} from 'vitest'
import {revealReportTarget} from './InspectionRunResultPage'
it('opens every containing details before scroll on initial and changed hash',()=>{
 document.body.innerHTML='<details><summary>outer</summary><details><summary>raw</summary><p id="check-a">UNKNOWN</p></details></details>'
 const target=document.getElementById('check-a')!;target.scrollIntoView=vi.fn(()=>{expect([...document.querySelectorAll('details')].every(x=>x.open)).toBe(true)})
 revealReportTarget('#check-a');expect(target.scrollIntoView).toHaveBeenCalledOnce()
 revealReportTarget('#missing');expect(target.textContent).toBe('UNKNOWN')
 document.body.innerHTML=''
})
