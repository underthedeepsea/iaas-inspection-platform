export function resourceCodeToSlug(code: string) {
  return code.toLowerCase().replaceAll('_', '-')
}

export function resourceSlugToCode(slug: string) {
  return slug.replaceAll('-', '_').toUpperCase()
}


export const isLaunchResource = (resource: { code: string }) => ['LLM_RUNTIME', 'GPU_POOL', 'HOST', 'K8S_CLUSTER'].includes(resource.code)

export const isCurrentInspectionResource = (resource: { code: string }) => resource.code !== 'KVM_CLUSTER'

export const isResourceInspectable = (resource: { code: string; release_state?: string; inspection_item_count: number }) =>
  resource.code !== 'K8S_CLUSTER' || (resource.release_state ? resource.release_state === 'READY' : resource.inspection_item_count > 0)
