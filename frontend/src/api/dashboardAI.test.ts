import { afterEach, expect, it, vi } from 'vitest'
import { streamDashboard } from './dashboardAI'

const facts = {source:'CODE',inspection_run_id:'run-1',check_count:1,checks:[]}
const answer = {answer:'不能逐字显示的模型正文',ai_status:'ACCEPTED',inspection_run_id:'run-1',source:{type:'AI',model:'test'},references:[],grounded_report:{source:'CODE',ai_status:'ACCEPTED',checks:[]}}
const frame = (event:string, data:unknown) => `event: ${event}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`
const good = frame('facts', facts) + frame('status',{stage:'generating'}) + frame('progress',{fragments:1,content_bytes:20}) + frame('result',answer) + frame('done',{outcome:'success'})
function mockStream(text:string, split = 3) {
  const bytes = new TextEncoder().encode(text)
  const cancel = vi.fn()
  const body = new ReadableStream<Uint8Array>({start(controller) {for (let i=0;i<bytes.length;i+=split) controller.enqueue(bytes.slice(i,i+split));controller.close()},cancel})
  const fetchMock = vi.fn().mockResolvedValue(new Response(body,{headers:{'Content-Type':'text/event-stream'}}))
  vi.stubGlobal('fetch', fetchMock)
  return {fetchMock,body,cancel}
}
afterEach(() => {vi.unstubAllGlobals();vi.useRealTimers()})
it('decodes split Chinese UTF8 and split SSE frames and posts exact context', async () => {
  const {fetchMock,body} = mockStream(good,1)
  const event = vi.fn()
  expect(await streamDashboard('env','中文问题','run-1',new AbortController().signal,event)).toEqual(answer)
  expect(event.mock.calls.map(([event])=>event.type)).toEqual(['facts','status','progress'])
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({environment_id:'env',question:'中文问题',inspection_run_id:'run-1'})
  expect(body.locked).toBe(false)
})
it('delivers actual progress while the final model response is still pending', async () => {
  let push!: ReadableStreamDefaultController<Uint8Array>
  const cancel=vi.fn()
  const body=new ReadableStream<Uint8Array>({start(controller){push=controller},cancel})
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(body,{headers:{'content-type':'text/event-stream'}})))
  const events=vi.fn()
  const promise=streamDashboard('env','question','run-1',new AbortController().signal,events)
  push.enqueue(new TextEncoder().encode(frame('facts',facts)+frame('progress',{fragments:4,content_bytes:80})))
  await vi.waitFor(()=>expect(events).toHaveBeenCalledTimes(2))
  expect(events.mock.calls[1][0].data.fragments).toBe(4)
  push.enqueue(new TextEncoder().encode(frame('result',answer)+frame('done',{outcome:'success'})))
  expect(await promise).toEqual(answer)
  expect(cancel).toHaveBeenCalledOnce()
  expect(body.locked).toBe(false)
})
it.each([
  frame('facts',facts)+frame('result',answer),
  frame('facts',facts)+frame('done',{outcome:'success'}),
  frame('facts',facts)+frame('result',{...answer,ai_status:'INVALID_PROTOCOL'})+frame('done',{outcome:'success'}),
  frame('facts',facts)+frame('result',{...answer,inspection_run_id:'wrong-run'})+frame('done',{outcome:'success'}),
  frame('facts',facts)+'event: progress\ndata: invalid JSON\n\n',
])('rejects incomplete or invalid terminal protocols with released reader', async text=>{
  const {body}=mockStream(text)
  await expect(streamDashboard('env','question','run-1',new AbortController().signal,()=>{})).rejects.toThrow(/未完整结束/)
  expect(body.locked).toBe(false)
})
it('honors error terminal and keeps previously delivered facts',async()=>{
  mockStream(frame('facts',facts)+frame('error',{code:'LLM_UNAVAILABLE',message:'AI暂不可用，事实保留'})+frame('done',{outcome:'error'}))
  const event=vi.fn()
  await expect(streamDashboard('env','question',undefined,new AbortController().signal,event)).rejects.toThrow('AI暂不可用，事实保留')
  expect(event.mock.calls[0][0].data).toEqual(facts)
})
it('retains existing JSON error shape for non2xx validation',async()=>{
  const error={error:{code:'VALIDATION_ERROR',message:'question无效'}}
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify(error),{status:400})))
  await expect(streamDashboard('env','question',undefined,new AbortController().signal,()=>{})).rejects.toEqual({response:{data:error}})
})
it.each(['user','deadline'])('aborts pending fetch on %s and enforces 130s wait',async kind=>{
  vi.useFakeTimers()
  let received!:AbortSignal
  vi.stubGlobal('fetch',vi.fn((_url,options)=>{received=options.signal;return new Promise((_resolve,reject)=>received.addEventListener('abort',()=>reject(received.reason)))}))
  const controller=new AbortController()
  const promise=streamDashboard('env','question',undefined,controller.signal,()=>{})
  const rejection=expect(promise).rejects.toThrow(kind==='deadline' ? /130 秒/ : /abort/i)
  if(kind==='user') controller.abort()
  else await vi.advanceTimersByTimeAsync(130_000)
  await rejection
  expect(received.aborted).toBe(true)
})
it('aborts during a pending reader read and releases its lock',async()=>{
  let push!:ReadableStreamDefaultController<Uint8Array>
  const body=new ReadableStream<Uint8Array>({start(controller){push=controller}})
  vi.stubGlobal('fetch',vi.fn((_url,options)=>{options.signal.addEventListener('abort',()=>push.error(options.signal.reason));return Promise.resolve(new Response(body,{headers:{'content-type':'text/event-stream'}}))}))
  const controller=new AbortController()
  const event=vi.fn()
  const promise=streamDashboard('env','question','run-1',controller.signal,event)
  push.enqueue(new TextEncoder().encode(frame('facts',facts)+frame('progress',{fragments:1,content_bytes:20})))
  await vi.waitFor(()=>expect(event).toHaveBeenCalledTimes(2))
  const rejection=expect(promise).rejects.toThrow(/abort/i)
  controller.abort()
  await rejection
  expect(body.locked).toBe(false)
})
