import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { LoginPage } from './LoginPage'

afterEach(() => vi.restoreAllMocks())

describe('LoginPage', () => {
  it('submits credentials and enters the requested route', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { user_id: 'user-1', username: 'operator', roles: ['viewer'] } } as never)
    render(<MemoryRouter initialEntries={['/login?next=/resources']}><Routes><Route element={<LoginPage />} path="/login" /><Route element={<h2>资源巡检页</h2>} path="/resources" /></Routes></MemoryRouter>)

    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'operator' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('heading', { name: '资源巡检页' })).toBeInTheDocument()
    expect(apiClient.post).toHaveBeenCalledWith('/auth/login', { username: 'operator', password: 'password' })
  })
})
