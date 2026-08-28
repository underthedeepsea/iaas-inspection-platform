import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../api/http'
import { AuthGuard, useAuthUser } from './AuthGuard'

afterEach(() => vi.restoreAllMocks())

function LocationProbe() {
  const location = useLocation()
  return <span>{location.pathname}{location.search}</span>
}

describe('AuthGuard', () => {
  it('redirects an expired session before rendering the private page', async () => {
    vi.spyOn(apiClient, 'get').mockRejectedValue({ response: { status: 401 } })

    render(
      <MemoryRouter initialEntries={['/resources/llm-runtime?environment=env-1']}>
        <Routes>
          <Route element={<AuthGuard><div>private page</div></AuthGuard>} path="*" />
          <Route element={<LocationProbe />} path="/login" />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('/login?next=%2Fresources%2Fllm-runtime%3Fenvironment%3Denv-1')).toBeInTheDocument())
    expect(screen.queryByText('private page')).not.toBeInTheDocument()
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
