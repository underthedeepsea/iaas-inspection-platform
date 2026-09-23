import { CodePluginsPage } from '../pages/CodePlugins/CodePluginsPage'
import { InspectionRunResultPage } from '../pages/InspectionRunResult/InspectionRunResultPage'
import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { AiRuntimePage } from '../pages/AiRuntime/AiRuntimePage'
import { DashboardPage } from '../pages/Dashboard/DashboardPage'
import { MainLayout } from '../layouts/MainLayout/MainLayout'
import { ProductInfoPage } from '../pages/ProductInfo/ProductInfoPage'
import { PromptsPage } from '../pages/Prompts/PromptsPage'
import { ResourceDetailPage } from '../pages/ResourceDetail/ResourceDetailPage'
import { ResourceRunDetailPage } from '../pages/ResourceRunDetail/ResourceRunDetailPage'
import { ResourcesPage } from '../pages/Resources/ResourcesPage'
import { RiskDetailPage } from '../pages/Risks/RiskDetailPage'
import { RisksPage } from '../pages/Risks/RisksPage'

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<MainLayout />}>
          <Route element={<CodePluginsPage />} path="/code-plugins" />
          <Route element={<CodePluginsPage />} path="/rules" />
          <Route element={<InspectionRunResultPage />} path="/inspection-runs/:runId" />
          <Route element={<DashboardPage />} path="/" />
          <Route element={<ResourcesPage />} path="/resources" />
          <Route element={<ResourceDetailPage />} path="/resources/:resourceType" />
          <Route element={<ResourceRunDetailPage />} path="/resources/:resourceType/runs/:runId" />
          <Route element={<RiskDetailPage />} path="/risks/:riskId" />
          <Route element={<RisksPage />} path="/risks" />
          <Route element={<AiRuntimePage />} path="/ai-runtime" />
          <Route element={<ProductInfoPage />} path="/about" />
          <Route element={<PromptsPage />} path="/prompts" />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
