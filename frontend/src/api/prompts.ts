import { apiClient } from './http'

export interface ExplanationPrompt {
  key: string
  name: string
  body: string
  revision: number
  updated_at: string
  hash: string
  default_body: string
  readonly_guard: string
  guard_version: string
  purposes: string[]
  provider: string
  model: string
}

const path = '/prompts/inspection-explanation'

export async function getExplanationPrompt() {
  const response = await apiClient.get<ExplanationPrompt>(path)
  return response.data
}

export async function saveExplanationPrompt(body: string, expectedRevision: number, token: string) {
  const response = await apiClient.patch<ExplanationPrompt>(path, { body, expected_revision: expectedRevision }, {
    headers: { 'X-Prompt-Admin-Token': token },
  })
  return response.data
}

export async function resetExplanationPrompt(expectedRevision: number, token: string) {
  const response = await apiClient.post<ExplanationPrompt>(`${path}/reset`, { expected_revision: expectedRevision }, {
    headers: { 'X-Prompt-Admin-Token': token },
  })
  return response.data
}
