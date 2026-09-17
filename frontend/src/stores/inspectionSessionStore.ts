import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

export type TerminalStatus = 'SUCCEEDED' | 'PARTIAL' | 'FAILED'
export interface InspectionSession {
  environmentId: string
  runId: string
  resourceTypes: string[]
  status: 'RUNNING' | TerminalStatus
  startedAt: string
}
interface InspectionSessionState {
  active: InspectionSession | null
  lastCompleted: InspectionSession | null
  start: (run: InspectionSession) => void
  finish: (runId: string, status: TerminalStatus) => void
  dismiss: (runId: string) => void
}
export const useInspectionSessionStore = create<InspectionSessionState>()(persist((set) => ({
  active: null,
  lastCompleted: null,
  start: (active) => set({ active }),
  finish: (runId, status) => set((state) => {
    if (state.active?.runId !== runId || state.active.status === status) return state
    const active = { ...state.active, status }
    return { active, lastCompleted: status === 'FAILED' ? state.lastCompleted : active }
  }),
  dismiss: (runId) => set((state) => state.active?.runId === runId && state.active.status !== 'RUNNING' ? { active: null } : state),
}), {
  name: 'iaas-inspection-session',
  storage: createJSONStorage(() => sessionStorage),
  partialize: ({ active, lastCompleted }) => ({ active, lastCompleted }),
}))
