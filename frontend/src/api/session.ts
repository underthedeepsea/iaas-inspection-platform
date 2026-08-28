import { apiClient } from './http'

export interface SessionUser {
  user_id: string
  username: string
  roles: string[]
}

export async function login(username: string, password: string) {
  const response = await apiClient.post<SessionUser>('/auth/login', { username, password })
  return response.data
}

export async function getCurrentUser() {
  const response = await apiClient.get<SessionUser>('/auth/me')
  return response.data
}
