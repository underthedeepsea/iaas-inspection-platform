export function resourceCodeToSlug(code: string) {
  return code.toLowerCase().replaceAll('_', '-')
}

export function resourceSlugToCode(slug: string) {
  return slug.replaceAll('-', '_').toUpperCase()
}


export const isLaunchResource = (resource: { code: string }) => ['CONTROL_PLANE', 'LLM_RUNTIME'].includes(resource.code)
