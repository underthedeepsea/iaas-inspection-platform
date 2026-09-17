import axios from 'axios'

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
    trace_id?: string
  }
}

export const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

export function getApiError(error: unknown): ApiErrorBody['error'] | null {
  if (axios.isAxiosError<ApiErrorBody>(error)) {
    return error.response?.data?.error ?? null
  }
  const response = (error as { response?: { data?: ApiErrorBody } } | null)?.response
  return response?.data?.error ?? null
}
