import { Alert, Button, Skeleton } from 'antd'
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { getApiError } from '../api/http'
import { getCurrentUser, login, type SessionUser } from '../api/session'

const AuthContext = createContext<SessionUser | null>(null)

export function useAuthUser() {
  return useContext(AuthContext)
}

function statusOf(error: unknown) {
  return (error as { response?: { status?: number } } | null)?.response?.status
}

export function AuthGuard({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const locationRef = useRef(location)
  locationRef.current = location
  const [user, setUser] = useState<SessionUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)

    const loadUser = async () => {
      try {
        const currentUser = await getCurrentUser()
        if (active) setUser(currentUser)
      } catch (requestError) {
        if (!active) return

        if (statusOf(requestError) === 401 && import.meta.env.DEV) {
          try {
            const demoUser = await login('e2e', 'e2e-password')
            if (active) setUser(demoUser)
          } catch (loginError) {
            if (active) setError(loginError)
          }
          return
        }

        if (statusOf(requestError) === 401) {
          const currentLocation = locationRef.current
          const next = `${currentLocation.pathname}${currentLocation.search}${currentLocation.hash}`
          navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true })
          return
        }
        setError(requestError)
      } finally {
        if (active) setLoading(false)
      }
    }

    void loadUser()
    return () => { active = false }
  }, [navigate, retry])

  if (loading) {
    return <main aria-label="正在验证登录状态" className="auth-loading"><span className="brand-mark" aria-hidden="true">巡</span><strong>IaaS 智能巡检</strong><Skeleton active paragraph={{ rows: 2 }} title={{ width: 180 }} /></main>
  }
  if (error) {
    const apiError = getApiError(error)
    return <main className="auth-loading" role="alert"><Alert description={apiError?.message ?? '暂时无法验证登录状态。'} message="登录状态检查失败" showIcon type="error" /><Button autoInsertSpace={false} onClick={() => setRetry((value) => value + 1)} type="primary">重试</Button></main>
  }
  if (!user) return null
  return <AuthContext.Provider value={user}>{children}</AuthContext.Provider>
}
