import type { ResourceType } from '../../api/resources'
import { resourceCodeToSlug } from './resourceRoutes'

import styles from './resourceHealth.module.css'

export function ResourceHealthCard({
  resource,
  onOpen,
}: {
  resource: ResourceType
  onOpen?: (resource: ResourceType) => void
}) {
  const health = resource.health_score == null ? '—' : String(Math.round(resource.health_score))
  return (
    <button
      className={styles.card}
      onClick={() => onOpen?.(resource)}
      type="button"
    >
      <span className={styles.cardHeader}>
        <span>
          <span className={styles.icon} aria-hidden="true">✦</span>
          <span className={styles.name}>{resource.name}</span>
        </span>
        <span className={styles.chevron} aria-hidden="true">→</span>
      </span>
      <span className={styles.healthRow}>
        <span className={styles.healthScore}>{health}</span>
        <span className={styles.healthLabel}>健康度</span>
      </span>
      <span className={styles.metrics}>
        <span>{resource.asset_count} 个资源对象</span>
        <span>巡检项 {resource.inspection_item_count}</span>
        <span>风险 {resource.risk_count}</span>
        <span className={resource.p1_count ? styles.danger : ''}>P1/P2 {resource.p1_count}/{resource.p2_count}</span>
      </span>
      <span className={styles.footer}>
        <span>{resource.last_inspection_at ? '最近已巡检' : '尚未巡检'}</span>
        <span>{resourceCodeToSlug(resource.code)}</span>
      </span>
    </button>
  )
}

