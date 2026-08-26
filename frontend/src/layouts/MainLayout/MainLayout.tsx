import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { getEnvironments, type Environment } from '../../api/environments'
import { useUiStore } from '../../stores/uiStore'

const navigationGroups = [
  {
    label: '运营总览',
    items: [
      ['每日巡检', '/'],
      ['资源巡检', '/resources'],
      ['风险中心', '/risks'],
      ['历史趋势', '/history'],
      ['待处置', '/pending'],
    ],
  },
  {
    label: '能力体系',
    items: [
      ['巡检能力', '/capabilities'],
      ['规则与经验', '/experiences'],
      ['能力演进', '/evolution'],
    ],
  },
  {
    label: '运行与说明',
    items: [
      ['AI 运行情况', '/ai-runtime'],
      ['产品说明', '/about'],
      ['系统设置', '/settings'],
    ],
  },
] as const

const pageTitles: Array<[string, string]> = [
  ['/', '每日巡检'],
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
  return pageTitles.find(([path]) => pathname === path || (path !== '/' && pathname.startsWith(`${path}/`)))?.[1] ?? '每日巡检'
}

export function MainLayout({ children }: { children?: ReactNode }) {
  const environmentId = useUiStore((state) => state.environmentId)
  const setEnvironmentId = useUiStore((state) => state.setEnvironmentId)
  const sidebarCollapsed = useUiStore((state) => state.sidebarCollapsed)
  const setSidebarCollapsed = useUiStore((state) => state.setSidebarCollapsed)
  const location = useLocation()
  const pageTitle = titleForPath(location.pathname)
  const [environments, setEnvironments] = useState<Environment[]>([])

  useEffect(() => {
    let active = true
    void getEnvironments().then((response) => {
      if (active) setEnvironments(response.items)
    }).catch(() => {
      if (active) setEnvironments([])
    })
    return () => { active = false }
  }, [])

  return (
    <div className={`app-shell${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
      <aside className="sidebar" aria-label="主导航">
        <NavLink className="brand" to="/" aria-label="返回每日巡检">
          <span className="brand-mark" aria-hidden="true">巡</span>
          <span>
            <strong>IaaS 智能巡检</strong>
            <small>控制面 · v0.2</small>
          </span>
        </NavLink>

        <button aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'} aria-pressed={sidebarCollapsed} className="sidebar-toggle" onClick={() => setSidebarCollapsed(!sidebarCollapsed)} type="button">
          <span aria-hidden="true">{sidebarCollapsed ? '→' : '←'}</span>
        </button>

        <nav className="nav-groups" aria-label="主导航">
          {navigationGroups.map((group) => (
            <div className="nav-group" key={group.label}>
              <span className="nav-label">{group.label}</span>
              {group.items.map(([label, to]) => (
                <NavLink
                  data-short-label={label.slice(0, 1)}
                  className={({ isActive }) => (isActive ? 'is-active' : undefined)}
                  end={to === '/'}
                  key={to}
                  to={to}
                >
                  {label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="status-dot" aria-hidden="true" />
          <span>环境数据由 API 提供</span>
          <span className="muted">v0.2</span>
        </div>
      </aside>

      <div className="app-frame">
        <header className="topbar">
          <div>
            <span className="eyebrow">INSPECTION CONTROL PLANE</span>
            <h1>{pageTitle}</h1>
          </div>
          <div className="topbar-actions">
            <label className="environment-picker">
              <span>环境</span>
              <select
                aria-label="巡检环境"
                value={environmentId ?? ''}
                onChange={(event) => setEnvironmentId(event.target.value || null)}
              >
                <option value="">全部环境</option>
                {environments.map((environment) => (
                  <option key={environment.id} value={environment.id}>
                    {environment.name} · {environment.slug}{environment.has_mock_data ? ' · 有模拟数据' : ''}
                  </option>
                ))}
              </select>
            </label>
            <span className="runtime-status"><span className="status-dot" aria-hidden="true" />AI 运行正常</span>
            <span className="topbar-user">管理员</span>
            <NavLink className="avatar" to="/settings" aria-label="打开系统设置">L</NavLink>
          </div>
        </header>

        <main className="main-content" id="app-main">
          {children ?? <Outlet />}
        </main>
      </div>
    </div>
  )
}
