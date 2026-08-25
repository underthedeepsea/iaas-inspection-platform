import { create } from 'zustand'

type UiState = {
  environmentId: string | null
  sidebarCollapsed: boolean
  inspectionDrawerOpen: boolean
  setEnvironmentId: (id: string | null) => void
  setSidebarCollapsed: (value: boolean) => void
  setInspectionDrawerOpen: (value: boolean) => void
}

export const useUiStore = create<UiState>((set) => ({
  environmentId: null,
  sidebarCollapsed: false,
  inspectionDrawerOpen: false,
  setEnvironmentId: (environmentId) => set({ environmentId }),
  setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
  setInspectionDrawerOpen: (inspectionDrawerOpen) => set({ inspectionDrawerOpen }),
}))

