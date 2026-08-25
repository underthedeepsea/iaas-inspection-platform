import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { DashboardPage } from '../pages/Dashboard/DashboardPage'
import { MainLayout } from '../layouts/MainLayout/MainLayout'

function Placeholder({ label }: { label: string }) {
  return <section aria-label={label}>{label}</section>
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <MainLayout>
        <Routes>
          <Route element={<DashboardPage />} path="/" />
          <Route element={<Placeholder label="资源巡检" />} path="/resources" />
          <Route element={<Placeholder label="资源详情" />} path="/resources/:resourceType" />
          <Route
            element={<Placeholder label="资源巡检详情" />}
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
