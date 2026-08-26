import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { AIConversation } from './AIConversation'

describe('AIConversation', () => {
  it('sends a follow-up question through the owned conversation', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        investigation_id: 'follow-up-1',
        turn_id: 'follow-up-1',
        events_url: '/api/v1/conversations/conversation-1/turns/follow-up-1/events',
      },
    } as never)
    const onTurnStarted = vi.fn()

    render(<AIConversation conversationId="conversation-1" onTurnStarted={onTurnStarted} />)
    fireEvent.change(screen.getByRole('textbox', { name: '询问 AI' }), {
      target: { value: '为什么健康度下降？' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/conversations/conversation-1/turns',
      { message: '为什么健康度下降？' },
    ))
    expect(onTurnStarted).toHaveBeenCalledWith('follow-up-1')
  })
})
