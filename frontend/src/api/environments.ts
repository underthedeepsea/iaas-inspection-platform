import { apiClient } from './http'

export interface Environment {
  id: string
  slug: string
  name: string
  environment_type: string
  timezone: string
  assets_count: number
  mock_dataset_count: number
  inspection_run_count: number
  has_mock_data: boolean
}

export async function getEnvironments() {
  const response = await apiClient.get<{ items: Environment[]; page: number; page_size: number; total: number }>('/environments')
  return response.data
}
