import { render, screen } from '@testing-library/react'
import { App } from './App'

it('renders the product shell', async () => {
  render(<App />)
  expect(await screen.findByText('IaaS 智能巡检')).toBeInTheDocument()
})
