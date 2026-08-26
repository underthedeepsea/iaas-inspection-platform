import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { login } from '../../api/session'

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await login(username.trim(), password)
      const next = new URLSearchParams(location.search).get('next')
      navigate(next?.startsWith('/') ? next : '/', { replace: true })
    } catch {
      setError('用户名或密码不正确。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <section aria-labelledby="login-title" className="login-card panel">
        <span className="brand-mark" aria-hidden="true">巡</span>
        <span className="eyebrow">INSPECTION CONTROL PLANE</span>
        <h1 id="login-title">登录 IaaS 智能巡检</h1>
        <p className="lede">使用已有平台账号进入巡检控制面。</p>
        <form onSubmit={(event) => void submit(event)}>
          <label><span>用户名</span><input autoComplete="username" onChange={(event) => setUsername(event.target.value)} required value={username} /></label>
          <label><span>密码</span><input autoComplete="current-password" onChange={(event) => setPassword(event.target.value)} required type="password" value={password} /></label>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button className="button button-primary" disabled={submitting} type="submit">{submitting ? '登录中…' : '登录'}</button>
        </form>
      </section>
    </main>
  )
}
