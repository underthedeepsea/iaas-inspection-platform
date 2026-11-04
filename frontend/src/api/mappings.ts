export type Binding = {standard_field: string; source_metric: string; source_type: string; source_unit: string; output_unit: string; conversion: string}
export type MetricMapping = Binding & {labels: Record<string, string>; window_seconds: number; step_seconds: number}
export type MappingContent = {schema_version: string; cluster: {cluster_uid: string; monitor_cluster_id: string; display_name: string}; metrics: MetricMapping[]}
export type MappingBundle = {bundle_id: string; environment_id: string; source_ref: string; cluster_uid: string; head_version: number; active_version?: number; active_revision_id?: string | null; revision_id: string; content: MappingContent; content_hash: string; status: string; validation: string}
export type MappingContext = {environments: {id: string; name: string}[]; catalog: Binding[]; source_ref: string; schema_version: string; unimplemented_fields: number}
export type MappingRevision = {version: number; content: MappingContent; content_hash: string; parent_revision: string | null; rollback_from: string | null; reason: string; actor_label: string; created_at: string}
export type MappingValidation = {validation_id: string; kind: 'STRUCTURE' | 'MOCK'; result: {status: string; errors: string[]}; binding: {revision_id:string; content_hash:string; environment_id:string; source_ref:string; cluster_uid:string; start:number; end:number; step:number}; valid_until:string}
export type MappingActivation = {activation_id:string; active_revision_id:string; active_version:number}
export class MappingHTTPError extends Error { constructor(public status: number, message: string) {super(message)} }
const prefix = '/api/v1/mappings/'
async function request<T>(path: string, body?: unknown): Promise<T> {
 const response = await fetch(prefix + path, {method: body === undefined ? 'GET' : 'POST', headers: body === undefined ? {} : {'Content-Type':'application/json'}, ...(body === undefined ? {} : {body:JSON.stringify(body)})})
 const payload = await response.json().catch(() => null)
 if (!response.ok) throw new MappingHTTPError(response.status, response.status === 409 ? '版本冲突；输入已保留。请取消编辑并重新读取后再提交。' : payload?.error?.message || `映射请求被拒绝（${response.status}）。`)
 return payload as T
}
const scope = (bundle: MappingBundle) => ({environment_id:bundle.environment_id, source_ref:bundle.source_ref, cluster_uid:bundle.cluster_uid})
export const mappingsAPI = {
 context() {return request<MappingContext>('context/')},
 list(environment: string) {return request<{items:MappingBundle[];has_more:boolean}>('bundles/?'+new URLSearchParams({environment_id:environment,source_ref:'demo-monitor'}))},
 detail(bundle: MappingBundle) {return request<MappingBundle>(`bundles/${bundle.bundle_id}/?`+new URLSearchParams(scope(bundle)))},
 create(environment: string, content: MappingContent, reason: string, actor: string) {return request<MappingBundle>('bundles/', {environment_id:environment,source_ref:'demo-monitor',cluster_uid:content.cluster.cluster_uid,monitor_cluster_id:content.cluster.monitor_cluster_id,content,expected_head:0,reason,actor_label:actor})},
 append(bundle: MappingBundle, content: MappingContent, reason: string, actor: string) {return request<MappingBundle>(`bundles/${bundle.bundle_id}/revisions/`, {...scope(bundle),content,expected_head:bundle.head_version,reason,actor_label:actor})},
 validate(bundle:MappingBundle,kind:'STRUCTURE'|'MOCK') {const windows=new Set(bundle.content.metrics.map(metric=>metric.window_seconds)), steps=new Set(bundle.content.metrics.map(metric=>metric.step_seconds));if(windows.size!==1||steps.size!==1)throw new MappingHTTPError(400,'模拟校验需要整包指标使用一致窗口与步长。');const duration=[...windows][0],step=[...steps][0],end=Math.floor(Date.now()/1000/step)*step-step;return request<MappingValidation>(`bundles/${bundle.bundle_id}/validate/`,{...scope(bundle),expected_head:bundle.head_version,kind,fixture:'complete',seed:1,start:end-duration,end,step})},
 activate(bundle:MappingBundle,validation_id:string,reason:string,actor:string,idempotency_key:string) {return request<MappingActivation>(`bundles/${bundle.bundle_id}/activate/`,{...scope(bundle),expected_head:bundle.head_version,expected_active:bundle.active_version??0,content_hash:bundle.content_hash,validation_id,idempotency_key,reason,actor_label:actor})},
 history(bundle: MappingBundle) {return request<{items:MappingRevision[];has_more:boolean}>(`bundles/${bundle.bundle_id}/revisions/?`+new URLSearchParams(scope(bundle)))},
 rollback(bundle: MappingBundle, version: number, reason: string, actor: string) {return request<MappingBundle>(`bundles/${bundle.bundle_id}/rollback/`, {...scope(bundle),target_version:version,expected_head:bundle.head_version,reason,actor_label:actor})},
}
