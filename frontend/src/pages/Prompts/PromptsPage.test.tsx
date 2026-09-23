import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { getExplanationPrompt, saveExplanationPrompt } from '../../api/prompts'
import { PromptsPage } from './PromptsPage'

vi.mock('../../api/prompts', () => ({
  getExplanationPrompt: vi.fn(),
  saveExplanationPrompt: vi.fn(),
  resetExplanationPrompt: vi.fn(),
}))

const prompt = {
  key: 'inspection-explanation', name: '巡检解读', body: '原正文', revision: 1,
  updated_at: '2026-09-23T00:00:00Z', hash: 'sha256:a', default_body: '默认正文',
  readonly_guard: '只解释CODE事实', guard_version: '1', purposes: ['dashboard_explanation', 'inspection_explanation'],
  provider: 'ollama', model: 'qwen3.5:4b-mlx',
}

afterEach(() => vi.clearAllMocks())

it('keeps editing read only until a temporary administrator credential is entered', async () => {
  vi.mocked(getExplanationPrompt).mockResolvedValue(prompt)
  render(<PromptsPage />)
  const body = await screen.findByRole('textbox', { name: '业务正文' })
  expect(body).toBeDisabled()
  expect(screen.getByText('原正文')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('管理凭证'), { target: { value: 'temporary' } })
  expect(body).not.toBeDisabled()
  fireEvent.change(body, { target: { value: '新正文' } })
  vi.mocked(saveExplanationPrompt).mockResolvedValue({ ...prompt, body: '新正文', revision: 2 })
  fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
  expect(await screen.findByText('已保存，当前 revision 2。')).toBeInTheDocument()
  expect(saveExplanationPrompt).toHaveBeenCalledWith('新正文', 1, 'temporary')
})

it('requires reload after a concurrent revision change', async () => {
  vi.mocked(getExplanationPrompt).mockResolvedValue(prompt)
  vi.mocked(saveExplanationPrompt).mockRejectedValue({ response: { data: { error: { code: 'PROMPT_REVISION_CONFLICT', message: 'conflict' } } } })
  render(<PromptsPage />)
  const body = await screen.findByRole('textbox', { name: '业务正文' })
  fireEvent.change(screen.getByLabelText('管理凭证'), { target: { value: 'temporary' } })
  fireEvent.change(body, { target: { value: '新正文' } })
  fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
  expect(await screen.findByText('提示词已被其他管理员修改。请重新加载，再决定如何编辑。')).toBeInTheDocument()
  expect(body).toBeDisabled()
  expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument()
})
