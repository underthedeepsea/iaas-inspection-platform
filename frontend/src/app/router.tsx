const PerformancePortraitsPage = lazy(() => import('../pages/PerformancePortraits/PerformancePortraitsPage').then(module => ({default: module.PerformancePortraitsPage})))
import { lazy, Suspense } from 'react'
import { PersistentMappingManagementPage as MappingManagementPage } from '../pages/MappingManagement/PersistentMappingManagementPage'
const CodePluginsPage = lazy(() => import('../pages/CodePlugins/CodePluginsPage').then(module => ({default: module.CodePluginsPage})))
const InspectionRunResultPage = lazy(() => import('../pages/InspectionRunResult/InspectionRunResultPage').then(module => ({default: module.InspectionRunResultPage})))
import { BrowserRouter, Route, Routes } from 'react-router-dom'

const AiRuntimePage = lazy(() => import('../pages/AiRuntime/AiRuntimePage').then(module => ({default: module.AiRuntimePage})))
const DashboardPage = lazy(() => import('../pages/Dashboard/DashboardPage').then(module => ({default: module.DashboardPage})))
const MainLayout = lazy(() => import('../layouts/MainLayout/MainLayout').then(module => ({default: module.MainLayout})))
const ProductInfoPage = lazy(() => import('../pages/ProductInfo/ProductInfoPage').then(module => ({default: module.ProductInfoPage})))
const PromptsPage = lazy(() => import('../pages/Prompts/PromptsPage').then(module => ({default: module.PromptsPage})))
const ResourceDetailPage = lazy(() => import('../pages/ResourceDetail/ResourceDetailPage').then(module => ({default: module.ResourceDetailPage})))
const ResourceRunDetailPage = lazy(() => import('../pages/ResourceRunDetail/ResourceRunDetailPage').then(module => ({default: module.ResourceRunDetailPage})))
const ResourcesPage = lazy(() => import('../pages/Resources/ResourcesPage').then(module => ({default: module.ResourcesPage})))
const RiskDetailPage = lazy(() => import('../pages/Risks/RiskDetailPage').then(module => ({default: module.RiskDetailPage})))
const RisksPage = lazy(() => import('../pages/Risks/RisksPage').then(module => ({default: module.RisksPage})))

export function AppRouter() {
  return (
    <BrowserRouter>
      <Suspense fallback={<p role="status">正在加载页面…</p>}>
      <Routes>
        <Route element={<MappingManagementPage />} path="/mappings" />
        <Route element={<MainLayout />}>
          <Route element={<CodePluginsPage />} path="/code-plugins" />
          <Route element={<CodePluginsPage />} path="/rules" />
          <Route element={<InspectionRunResultPage />} path="/inspection-runs/:runId" />
          <Route element={<DashboardPage />} path="/" />
          <Route element={<ResourcesPage />} path="/resources" />
          <Route element={<PerformancePortraitsPage />} path="/performance-profiles" />
          <Route element={<PerformancePortraitsPage />} path="/performance-profiles/:kind/:id" />
          <Route element={<ResourceDetailPage />} path="/resources/:resourceType" />
          <Route element={<ResourceRunDetailPage />} path="/resources/:resourceType/runs/:runId" />
          <Route element={<RiskDetailPage />} path="/risks/:riskId" />
          <Route element={<RisksPage />} path="/risks" />
          <Route element={<AiRuntimePage />} path="/ai-runtime" />
          <Route element={<ProductInfoPage />} path="/about" />
          <Route element={<PromptsPage />} path="/prompts" />
        </Route>
      </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
