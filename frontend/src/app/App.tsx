import { QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'

import { queryClient } from './queryClient'
import { AppRouter } from './router'
import { appTheme } from './theme'

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider theme={appTheme}>
        <AppRouter />
      </ConfigProvider>
    </QueryClientProvider>
  )
}
