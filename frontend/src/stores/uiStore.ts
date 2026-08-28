import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

type UiState = {
  environmentId: string | null
  sidebarCollapsed: boolean
  inspectionDrawerOpen: boolean
  setEnvironmentId: (id: string | null) => void
  setSidebarCollapsed: (value: boolean) => void
  setInspectionDrawerOpen: (value: boolean) => void
}

const memoryStorage: Storage = {
  getItem: () => null,
  setItem: () => undefined,
  removeItem: () => undefined,
  clear: () => undefined,
  key: () => null,
  length: 0,
}

function browserStorage() {
  try {
    const storage = window.localStorage
    return typeof storage.getItem === 'function' && typeof storage.setItem === 'function' ? storage : memoryStorage
  } catch {
    return memoryStorage
  }
}

export const useUiStore = create<UiState>()(persist((set) => ({
  environmentId: null,
  sidebarCollapsed: false,
  inspectionDrawerOpen: false,
  setEnvironmentId: (environmentId) => set({ environmentId }),
  setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
  setInspectionDrawerOpen: (inspectionDrawerOpen) => set({ inspectionDrawerOpen }),
}), {
  name: 'iaas-inspection-ui',
  storage: createJSONStorage(browserStorage),
  partialize: (state) => ({
    environmentId: state.environmentId,
    sidebarCollapsed: state.sidebarCollapsed,
    inspectionDrawerOpen: state.inspectionDrawerOpen,
  }),
}))
