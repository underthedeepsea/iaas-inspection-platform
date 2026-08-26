import { useState } from 'react'

export function AIConversation() {
  const [question, setQuestion] = useState('')
  return (
    <section className="ai-conversation">
      <div className="section-heading"><div><span className="eyebrow">FOLLOW-UP</span><h3>询问 AI</h3></div><span className="legend">只读调查</span></div>
      <div className="ai-conversation-form">
        <input aria-label="询问 AI" onChange={(event) => setQuestion(event.target.value)} placeholder="针对当前资源继续提问" value={question} />
        <button className="button button-primary" disabled={!question.trim()} type="button">发送</button>
      </div>
    </section>
  )
}
