import { useEffect, useState } from 'react'
import { Alert, Button, Input, Popconfirm } from 'antd'

import { getApiError } from '../../api/http'
import {
  getExplanationPrompt, resetExplanationPrompt, saveExplanationPrompt,
  type ExplanationPrompt,
} from '../../api/prompts'

export function PromptsPage() {
  const [prompt, setPrompt] = useState<ExplanationPrompt | null>(null)
  const [body, setBody] = useState('')
  const [token, setToken] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [conflict, setConflict] = useState(false)

  const reload = async () => {
    setLoading(true)
    try {
      const latest = await getExplanationPrompt()
      setPrompt(latest)
      setBody(latest.body)
      setConflict(false)
      setMessage('')
    } catch {
      setMessage('提示词读取失败，请重试。')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void reload() }, [])

  const write = async (reset: boolean) => {
    if (!prompt || !token.trim()) return
    setSaving(true)
    try {
      const updated = reset
        ? await resetExplanationPrompt(prompt.revision, token)
        : await saveExplanationPrompt(body, prompt.revision, token)
      setPrompt(updated)
      setBody(updated.body)
      setConflict(false)
      setMessage(reset ? `已恢复默认，当前 revision ${updated.revision}。` : `已保存，当前 revision ${updated.revision}。`)
    } catch (error) {
      const code = getApiError(error)?.code
      setConflict(code === 'PROMPT_REVISION_CONFLICT')
      setMessage(code === 'PROMPT_REVISION_CONFLICT'
        ? '提示词已被其他管理员修改。请重新加载，再决定如何编辑。'
        : code === 'PROMPT_ADMIN_REQUIRED' ? '管理凭证无效或服务端未配置。' : '保存失败，请检查正文并重试。')
    } finally {
      setSaving(false)
    }
  }

  return <section className="view" aria-labelledby="prompts-title">
    <div className="page-heading"><div><span className="eyebrow">AI EXPLANATION</span><h2 id="prompts-title">提示词</h2><p className="lede">管理首页与资源巡检解读共用的业务说明。CODE 结论和风险由巡检规则决定。</p></div></div>
    {message ? <Alert type={conflict ? 'warning' : 'info'} message={message} showIcon /> : null}
    {loading ? <div className="empty-state" role="status">正在读取提示词…</div> : prompt ? <div className="panel panel-large">
      <dl className="definition-list">
        <div><dt>Key</dt><dd>{prompt.key}</dd></div>
        <div><dt>当前 revision</dt><dd>{prompt.revision}</dd></div>
        <div><dt>模型</dt><dd>{prompt.provider} · {prompt.model}</dd></div>
        <div><dt>生效入口</dt><dd>首页解读、资源 / Run 解读</dd></div>
        <div><dt>只读安全约束</dt><dd>{prompt.readonly_guard}</dd></div>
      </dl>
      <label htmlFor="prompt-body">业务正文</label>
      <Input.TextArea id="prompt-body" aria-label="业务正文" disabled={!token.trim() || conflict} maxLength={600} onChange={event => setBody(event.target.value)} rows={5} value={body} />
      <p>{body.length} / 600 字符</p>
      <label htmlFor="prompt-admin-token">管理凭证（仅在本页内存中使用）</label>
      <Input.Password id="prompt-admin-token" aria-label="管理凭证" autoComplete="off" onChange={event => setToken(event.target.value)} value={token} />
      <div className="prompt-actions">
        <Button disabled={!token.trim() || conflict || !body.trim() || body.length > 600 || body === prompt.body} loading={saving} onClick={() => void write(false)} type="primary">保存</Button>
        <Popconfirm title="恢复默认提示词？" description="这会创建新的 revision。" onConfirm={() => void write(true)} okText="恢复" cancelText="取消">
          <Button disabled={!token.trim() || conflict} loading={saving}>恢复默认</Button>
        </Popconfirm>
        <Button onClick={() => void reload()}>重新加载</Button>
      </div>
    </div> : <div className="empty-state" role="alert">提示词不可用。<Button onClick={() => void reload()}>重试</Button></div>}
  </section>
}
