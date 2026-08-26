import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { DashboardPage } from '../pages/Dashboard/DashboardPage'
import { MainLayout } from '../layouts/MainLayout/MainLayout'
import { ResourcesPage } from '../pages/Resources/ResourcesPage'
import { ResourceDetailPage } from '../pages/ResourceDetail/ResourceDetailPage'
import { ResourceRunDetailPage } from '../pages/ResourceRunDetail/ResourceRunDetailPage'
import { ProductInfoPage } from '../pages/ProductInfo/ProductInfoPage'
import { RiskDetailPage } from '../pages/Risks/RiskDetailPage'
import { RisksPage } from '../pages/Risks/RisksPage'
import { SectionOverviewPage } from '../pages/SectionOverview/SectionOverviewPage'

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
          <Route element={<RiskDetailPage />} path="/risks/:riskId" />
          <Route element={<RisksPage />} path="/risks" />
          <Route element={<SectionOverviewPage page="history" />} path="/history" />
          <Route element={<SectionOverviewPage page="pending" />} path="/pending" />
          <Route element={<SectionOverviewPage page="capabilities" />} path="/capabilities" />
          <Route element={<SectionOverviewPage page="experiences" />} path="/experiences" />
          <Route element={<SectionOverviewPage page="evolution" />} path="/evolution" />
          <Route element={<SectionOverviewPage page="ai-runtime" />} path="/ai-runtime" />
          <Route element={<ProductInfoPage />} path="/about" />
          <Route element={<SectionOverviewPage page="settings" />} path="/settings" />
        </Routes>
      </MainLayout>
    </BrowserRouter>
  )
}
