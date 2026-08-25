import { useState } from 'react'

export function AIConversation() {
  const [question, setQuestion] = useState('')
  return (
    <section>
      <h3>询问 AI</h3>
      <div style={{ display: 'flex', gap: 8 }}>
        <input aria-label="询问 AI" onChange={(event) => setQuestion(event.target.value)} placeholder="针对当前资源继续提问" value={question} />
        <button disabled={!question.trim()} type="button">发送</button>
      </div>
    </section>
  )
}

