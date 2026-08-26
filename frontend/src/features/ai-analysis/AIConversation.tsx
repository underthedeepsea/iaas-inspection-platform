import { useState } from 'react'

import { createConversationTurn } from '../../api/investigations'

export function AIConversation({
  conversationId,
  onTurnStarted,
}: {
  conversationId?: string | null
  onTurnStarted?: (investigationId: string) => void
}) {
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  const send = async () => {
    const message = question.trim()
    if (!message || !conversationId || sending) return
    setSending(true)
    setError('')
    try {
      const response = await createConversationTurn(conversationId, message)
      setQuestion('')
      onTurnStarted?.(response.investigation_id || response.turn_id)
    } catch {
      setError('问题发送失败，请稍后重试')
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="ai-conversation">
      <div className="section-heading"><div><span className="eyebrow">FOLLOW-UP</span><h3>询问 AI</h3></div><span className="legend">只读调查</span></div>
      <form className="ai-conversation-form" onSubmit={(event) => { event.preventDefault(); void send() }}>
        <input aria-label="询问 AI" onChange={(event) => setQuestion(event.target.value)} placeholder="针对当前资源继续提问" value={question} />
        <button className="button button-primary" disabled={!question.trim() || !conversationId || sending} type="submit">{sending ? '发送中…' : '发送'}</button>
      </form>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {!conversationId ? <p className="muted">启动一次 AI 分析后即可继续追问。</p> : null}
    </section>
  )
}
