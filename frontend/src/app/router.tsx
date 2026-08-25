import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { DashboardPage } from '../pages/Dashboard/DashboardPage'
import { MainLayout } from '../layouts/MainLayout/MainLayout'
import { ResourcesPage } from '../pages/Resources/ResourcesPage'
import { ResourceDetailPage } from '../pages/ResourceDetail/ResourceDetailPage'
import { ResourceRunDetailPage } from '../pages/ResourceRunDetail/ResourceRunDetailPage'

function Placeholder({ label }: { label: string }) {
  return <section aria-label={label}>{label}</section>
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <MainLayout>
        <Routes>
          <Route element={<DashboardPage />} path="/" />
          <Route element={<ResourcesPage />} path="/resources" />
          <Route element={<ResourceDetailPage />} path="/resources/:resourceType" />
          <Route
            element={<ResourceRunDetailPage />}
            path="/resources/:resourceType/runs/:runId"
          />
          <Route element={<Placeholder label="风险中心" />} path="/risks" />
          <Route element={<Placeholder label="巡检能力" />} path="/capabilities" />
          <Route element={<Placeholder label="能力演进" />} path="/evolution" />
          <Route element={<Placeholder label="AI 运行" />} path="/ai-runtime" />
          <Route element={<Placeholder label="关于平台" />} path="/about" />
        </Routes>
      </MainLayout>
    </BrowserRouter>
  )
}
