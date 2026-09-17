import { apiClient } from './http'

export interface ProductInfo {
  product_name: string
  data_mode: string
  llm_provider: string
  security_mode: string
  versions?: Record<string, string>
}

export async function getProductInfo() {
  const response = await apiClient.get<ProductInfo>('/product-info')
  return response.data
}

export function displayDataMode(value?: string | null) {
  return value?.toUpperCase() === 'MOCK' ? '环境数据' : value || '读取中…'
}
