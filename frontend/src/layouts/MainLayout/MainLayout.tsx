import { Select } from 'antd'
import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useSearchParams } from 'react-router-dom'

import { getEnvironments, type Environment } from '../../api/environments'
import { useUiStore } from '../../stores/uiStore'

const primaryNavigation = [
  ['总览', '/'],
  ['资源巡检', '/resources'],
  ['风险中心', '/risks'],
  ['规则库', '/rules'],
  ['产品说明', '/about'],
] as const

const pageTitles: Array<[string, string]> = [
  ['/', '总览'],
  ['/code-plugins', '代码插件'],
  ['/rules', '规则库'],
  ['/inspection-runs', '本次巡检结果'],
  ['/risks', '风险中心'],
  ['/ai-runtime', 'AI 运行情况'],
  ['/about', '产品说明'],
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
  const setEnvironmentName = useUiStore((state) => state.setEnvironmentName)
  const setEnvironmentId = useUiStore((state) => state.setEnvironmentId)
  const sidebarCollapsed = useUiStore((state) => state.sidebarCollapsed)
  const setSidebarCollapsed = useUiStore((state) => state.setSidebarCollapsed)
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const pageTitle = titleForPath(location.pathname)
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [environmentsLoading, setEnvironmentsLoading] = useState(true)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  const urlEnvironmentId = searchParams.get('environment')

  useEffect(() => {
    if (environmentsLoading) return
    const resolved = resolveEnvironmentId(environments, urlEnvironmentId, environmentId)
    const environment = environments.find(row => row.id === resolved)
    setEnvironmentName(environment ? `${environment.name} · ${environment.slug}` : '当前环境')
    if (resolved !== environmentId) setEnvironmentId(resolved)
    if (resolved !== urlEnvironmentId) {
      const nextParams = new URLSearchParams(searchParams)
      if (resolved) nextParams.set('environment', resolved)
      else nextParams.delete('environment')
      setSearchParams(nextParams, { replace: true })
    }
  }, [environmentId, environments, environmentsLoading, searchParams, setEnvironmentName, setEnvironmentId, setSearchParams, urlEnvironmentId])

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

  const closeMobileNav = () => setMobileNavOpen(false)

  return (
    <div className={`app-shell${sidebarCollapsed ? ' sidebar-collapsed' : ''}${mobileNavOpen ? ' mobile-nav-open' : ''}`}>
      <a className="skip-link" href="#app-main">跳转到主要内容</a>
      <aside className={`sidebar${mobileNavOpen ? ' is-open' : ''}`} id="main-navigation" aria-label="主导航">
        <NavLink className="brand" onClick={closeMobileNav} to="/" aria-label="返回每日巡检">
          <span className="brand-mark" aria-hidden="true">巡</span>
          <span>
            <strong>IaaS 智能巡检</strong>
            <small>Cloud operations</small>
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

        </nav>

        <div className="sidebar-footer">
          <span className="status-dot" aria-hidden="true" />
          <span>数据来源：模拟巡检数据</span>
        </div>
      </aside>
      {mobileNavOpen ? <button aria-label="关闭主导航遮罩" className="mobile-nav-backdrop" onClick={closeMobileNav} type="button" /> : null}

      <div className="app-frame">
        <header className="topbar">
          <div className="topbar-title">
            <span>工作台 /</span>
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
                    label: `${environment.name} · ${environment.slug}`,
                  })),
                ]}
                value={environmentId ?? ''}
              />
            </label>
            <span className="runtime-status"><span className="status-dot" aria-hidden="true" />CODE 确定性巡检</span>
          </div>
        </header>

        <main className="main-content" id="app-main">
          {children ?? <Outlet />}
        </main>
      </div>
    </div>
  )
}
