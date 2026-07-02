import { useEffect, useState } from 'react'
import { Card, Select, Input, Button, Space, Typography, Empty, Tag, message, InputNumber } from 'antd'
import { SendOutlined, ClearOutlined } from '@ant-design/icons'
import { listCatalogModels, playgroundChat } from '../api/index.js'
import { useAuthStore } from '../stores/authStore.js'

const ROLE_COLOR = { user: 'blue', assistant: 'green', system: 'default' }

export default function Playground() {
  const orgId = useAuthStore((s) => s.currentOrgId)
  const [models, setModels] = useState([])
  const [model, setModel] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [temperature, setTemperature] = useState(null)
  const [loading, setLoading] = useState(false)
  const [lastUsage, setLastUsage] = useState(null)

  useEffect(() => {
    listCatalogModels().then((d) => {
      const chat = d.data.filter((m) => m.mode === 'chat')
      setModels(chat.map((m) => ({ value: m.id, label: `${m.id} · ${m.provider}` })))
      if (chat.length && !model) setModel(chat.find((m) => m.id === 'gemini-2.5-flash')?.id || chat[0].id)
    })
  }, [])

  const send = async () => {
    if (!input.trim() || !model) return
    const next = [...messages, { role: 'user', content: input }]
    setMessages(next); setInput(''); setLoading(true)
    try {
      const data = await playgroundChat(orgId, {
        model, messages: next,
        temperature: temperature ?? undefined,
      })
      const reply = data.choices?.[0]?.message?.content ?? '(空)'
      setMessages([...next, { role: 'assistant', content: reply }])
      setLastUsage(data.usage)
    } catch (e) {
      message.error(e.response?.data?.detail?.error?.message || e.response?.data?.detail || '调用失败（可能上游未配置凭证）')
      setMessages(next)
    } finally { setLoading(false) }
  }

  return (
    <Card
      title="Playground · 站内试聊"
      extra={
        <Space>
          <Select showSearch optionFilterProp="label" style={{ width: 280 }} value={model} onChange={setModel} options={models} placeholder="选择模型" />
          <InputNumber size="small" min={0} max={2} step={0.1} value={temperature} onChange={setTemperature} placeholder="temp" style={{ width: 90 }} />
          <Button icon={<ClearOutlined />} onClick={() => { setMessages([]); setLastUsage(null) }}>清空</Button>
        </Space>
      }
    >
      <div style={{ minHeight: 320, maxHeight: 460, overflowY: 'auto', padding: 8, background: '#fafafa', borderRadius: 8, marginBottom: 12 }}>
        {messages.length === 0 ? <Empty description="选择模型后开始对话" style={{ marginTop: 80 }} /> : messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 12 }}>
            <Tag color={ROLE_COLOR[m.role]}>{m.role}</Tag>
            <Typography.Paragraph style={{ display: 'inline', whiteSpace: 'pre-wrap' }}>{m.content}</Typography.Paragraph>
          </div>
        ))}
      </div>
      {lastUsage && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          上次用量：prompt {lastUsage.prompt_tokens} · completion {lastUsage.completion_tokens} · total {lastUsage.total_tokens}
        </Typography.Text>
      )}
      <Space.Compact style={{ width: '100%', marginTop: 8 }}>
        <Input.TextArea
          value={input} onChange={(e) => setInput(e.target.value)}
          autoSize={{ minRows: 1, maxRows: 4 }} placeholder="输入消息，Enter 发送 / Shift+Enter 换行"
          onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send() } }}
        />
        <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={send}>发送</Button>
      </Space.Compact>
    </Card>
  )
}
