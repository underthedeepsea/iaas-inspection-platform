import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../api/http'
import { AuthGuard, useAuthUser } from './AuthGuard'

afterEach(() => vi.restoreAllMocks())

describe('AuthGuard', () => {
  it('silently signs into the local demo session before rendering the private page', async () => {
    vi.spyOn(apiClient, 'get').mockRejectedValue({ response: { status: 401 } })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { user_id: 'demo-user', username: 'e2e', roles: ['operator', 'viewer'] },
    } as never)

    render(
      <MemoryRouter initialEntries={['/resources/llm-runtime?environment=env-1']}>
        <Routes>
          <Route element={<AuthGuard><div>private page</div></AuthGuard>} path="*" />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('private page')).toBeInTheDocument()
    expect(post).toHaveBeenCalledWith('/auth/login', { username: 'e2e', password: 'e2e-password' })
  })

  it('provides the authenticated username and roles to the private page', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { user_id: 'user-1', username: 'operator', roles: ['viewer'] } } as never)

    function PrivatePage() {
      const user = useAuthUser()
      return <div>{user?.username} · {user?.roles.join(',')}</div>
    }

    render(
      <MemoryRouter initialEntries={['/']}>
        <AuthGuard><PrivatePage /></AuthGuard>
      </MemoryRouter>,
    )

    expect(await screen.findByText('operator · viewer')).toBeInTheDocument()
    expect(apiClient.get).toHaveBeenCalledWith('/auth/me')
  })
})
