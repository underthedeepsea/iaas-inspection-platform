import { render, screen } from '@testing-library/react'
import { App } from './App'

it('renders the product shell', () => {
  render(<App />)
  expect(screen.getByText('IaaS 智能巡检')).toBeInTheDocument()
})
