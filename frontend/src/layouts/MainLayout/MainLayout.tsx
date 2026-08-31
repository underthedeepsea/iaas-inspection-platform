import { Select } from 'antd'
import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useSearchParams } from 'react-router-dom'

import { getEnvironments, type Environment } from '../../api/environments'
import { useUiStore } from '../../stores/uiStore'
import { useAuthUser } from '../../app/AuthGuard'

const primaryNavigation = [
  ['总览', '/'],
  ['资源巡检', '/resources'],
  ['风险中心', '/risks'],
  ['巡检能力', '/capabilities'],
  ['能力演进', '/evolution'],
  ['AI运行', '/ai-runtime'],
  ['产品说明', '/about'],
] as const

const secondaryNavigation = [
  ['历史趋势', '/history'],
  ['待处置', '/pending'],
  ['规则与经验', '/experiences'],
  ['系统设置', '/settings'],
] as const

const pageTitles: Array<[string, string]> = [
  ['/', '总览'],
  ['/risks', '风险中心'],
  ['/history', '历史趋势'],
  ['/pending', '待处置'],
  ['/capabilities', '巡检能力'],
  ['/experiences', '规则与经验'],
  ['/evolution', '能力演进'],
  ['/ai-runtime', 'AI 运行情况'],
  ['/about', '产品说明'],
  ['/settings', '系统设置'],
  ['/resources', '资源巡检'],
]

function titleForPath(pathname: string) {
  return pageTitles.find(([path]) => pathname === path || (path !== '/' && pathname.startsWith(`${path}/`)))?.[1] ?? '总览'
}

export function resolveEnvironmentId<T extends { id: string }>(environments: T[], urlId?: string | null, storedId?: string | null) {
  const available = new Set(environments.map((environment) => environment.id))
  if (urlId && available.has(urlId)) return urlId
  if (storedId && available.has(storedId)) return storedId
  return environments[0]?.id ?? null
}

export function MainLayout({ children }: { children?: ReactNode }) {
  const environmentId = useUiStore((state) => state.environmentId)
  const setEnvironmentId = useUiStore((state) => state.setEnvironmentId)
  const sidebarCollapsed = useUiStore((state) => state.sidebarCollapsed)
  const setSidebarCollapsed = useUiStore((state) => state.setSidebarCollapsed)
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const pageTitle = titleForPath(location.pathname)
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [environmentsLoading, setEnvironmentsLoading] = useState(true)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const user = useAuthUser()

  const urlEnvironmentId = searchParams.get('environment')

  useEffect(() => {
    if (environmentsLoading) return
    const resolved = resolveEnvironmentId(environments, urlEnvironmentId, environmentId)
    if (resolved !== environmentId) setEnvironmentId(resolved)
    if (resolved !== urlEnvironmentId) {
      const nextParams = new URLSearchParams(searchParams)
      if (resolved) nextParams.set('environment', resolved)
      else nextParams.delete('environment')
      setSearchParams(nextParams, { replace: true })
    }
  }, [environmentId, environments, environmentsLoading, searchParams, setEnvironmentId, setSearchParams, urlEnvironmentId])

  useEffect(() => {
    let active = true
    void getEnvironments().then((response) => {
      if (active) setEnvironments(response.items)
    }).catch(() => {
      if (active) setEnvironments([])
    }).finally(() => {
      if (active) setEnvironmentsLoading(false)
    })
    return () => { active = false }
  }, [])

  const changeEnvironment = (value: string) => {
    const next = value || null
    setEnvironmentId(next)
    const nextParams = new URLSearchParams(searchParams)
    if (next) nextParams.set('environment', next)
    else nextParams.delete('environment')
    setSearchParams(nextParams)
  }

  const username = user?.username ?? '未登录'
  const roles = user?.roles.length ? user.roles.join(' · ') : '未建立会话'
  const avatarInitial = user?.username?.trim().slice(0, 1).toUpperCase() || '?'
  const closeMobileNav = () => setMobileNavOpen(false)

  return (
    <div className={`app-shell${sidebarCollapsed ? ' sidebar-collapsed' : ''}${mobileNavOpen ? ' mobile-nav-open' : ''}`}>
      <aside className={`sidebar${mobileNavOpen ? ' is-open' : ''}`} id="main-navigation" aria-label="主导航">
        <NavLink className="brand" onClick={closeMobileNav} to="/" aria-label="返回每日巡检">
          <span className="brand-mark" aria-hidden="true">巡</span>
          <span>
            <strong>IaaS 智能巡检</strong>
            <small>控制面</small>
          </span>
        </NavLink>

        <button aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'} aria-pressed={sidebarCollapsed} className="sidebar-toggle" onClick={() => setSidebarCollapsed(!sidebarCollapsed)} type="button">
          <span aria-hidden="true">{sidebarCollapsed ? '→' : '←'}</span>
        </button>

        <nav className="nav-groups" aria-label="主导航">
          <div className="nav-group nav-primary">
            <span className="nav-label">工作台</span>
            {primaryNavigation.map(([label, to]) => (
              <NavLink data-short-label={label.slice(0, 1)} className={({ isActive }) => (isActive ? 'is-active' : undefined)} end={to === '/'} key={to} onClick={closeMobileNav} to={to}>{label}</NavLink>
            ))}
          </div>
          <details className="nav-more">
            <summary>更多</summary>
            <div className="nav-group">
              {secondaryNavigation.map(([label, to]) => (
                <NavLink data-short-label={label.slice(0, 1)} className={({ isActive }) => (isActive ? 'is-active' : undefined)} key={to} onClick={closeMobileNav} to={to}>{label}</NavLink>
              ))}
            </div>
          </details>
        </nav>

        <div className="sidebar-footer">
          <span className="status-dot" aria-hidden="true" />
          <span>环境数据由 API 提供</span>
        </div>
      </aside>
      {mobileNavOpen ? <button aria-label="关闭主导航遮罩" className="mobile-nav-backdrop" onClick={closeMobileNav} type="button" /> : null}

      <div className="app-frame">
        <header className="topbar">
          <div className="topbar-title">
            <span>今日工作区</span>
            <h1>{pageTitle}</h1>
          </div>
          <div className="topbar-actions">
            <button aria-controls="main-navigation" aria-expanded={mobileNavOpen} aria-label={mobileNavOpen ? '关闭主导航' : '打开主导航'} className="menu-toggle" onClick={() => setMobileNavOpen((open) => !open)} type="button"><span aria-hidden="true">菜单</span></button>
            <label className="environment-picker">
              <span>环境</span>
              <Select
                aria-label="巡检环境"
                className="environment-select"
                onChange={changeEnvironment}
                options={[
                  { value: '', label: '全部环境' },
                  ...environments.map((environment) => ({
                    value: environment.id,
                    label: `${environment.name} · ${environment.slug}${environment.has_mock_data ? ' · 有模拟数据' : ''}`,
                  })),
                ]}
                value={environmentId ?? ''}
              />
            </label>
            <span className="runtime-status"><span className="status-dot" aria-hidden="true" />AI 运行正常</span>
            <span className="topbar-user"><strong>{username}</strong><small>{roles}</small></span>
            <NavLink className="avatar" to="/settings" aria-label="打开系统设置">{avatarInitial}</NavLink>
          </div>
        </header>

        <main className="main-content" id="app-main">
          {children ?? <Outlet />}
        </main>
      </div>
    </div>
  )
}
