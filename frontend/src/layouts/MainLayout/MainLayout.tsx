import type { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { useUiStore } from '../../stores/uiStore'
import styles from './MainLayout.module.css'

const navigation = [
  ['总览', '/'],
  ['资源巡检', '/resources'],
  ['风险中心', '/risks'],
  ['巡检能力', '/capabilities'],
  ['能力演进', '/evolution'],
  ['AI 运行', '/ai-runtime'],
] as const

export function MainLayout({ children }: { children?: ReactNode }) {
  const environmentId = useUiStore((state) => state.environmentId)
  const setEnvironmentId = useUiStore((state) => state.setEnvironmentId)

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.brandMark} aria-hidden="true">
            ✦
          </span>
          <span>IaaS 智能巡检</span>
        </div>
        <div className={styles.headerControls}>
          <label className={styles.environment}>
            <span>环境</span>
            <select
              aria-label="巡检环境"
              value={environmentId ?? ''}
              onChange={(event) => setEnvironmentId(event.target.value || null)}
            >
              <option value="">租户区生产环境</option>
              <option value="staging">租户区预发布环境</option>
            </select>
          </label>
          <span className={styles.runtime}>
            <span className={styles.runtimeDot} aria-hidden="true" />
            AI 运行正常
          </span>
          <span aria-label="当前用户">管理员</span>
        </div>
      </header>
      <div className={styles.body}>
        <aside className={styles.sidebar}>
          <nav className={styles.nav} aria-label="主导航">
            {navigation.map(([label, to]) => (
              <NavLink
                className={({ isActive }) =>
                  `${styles.navLink} ${isActive ? styles.navLinkActive : ''}`
                }
                end={to === '/'}
                key={to}
                to={to}
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </aside>
        <main className={styles.content}>{children ?? <Outlet />}</main>
      </div>
    </div>
  )
}

