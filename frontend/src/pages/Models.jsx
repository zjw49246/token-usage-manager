import { useEffect, useMemo, useState } from 'react'
import { Card, Table, Tag, Input, Select, Space, Typography, Badge } from 'antd'
import { SafetyCertificateOutlined } from '@ant-design/icons'
import { listCatalogModels } from '../api/index.js'

const PROVIDER_COLOR = {
  openai: 'green', anthropic: 'volcano', google: 'geekblue',
  deepseek: 'purple', mistral: 'magenta', groq: 'orange', xai: 'cyan',
  'volcengine-ark': 'purple',
}

function price(v) {
  return v == null ? '—' : `$${v}`
}

export default function Models() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [provider, setProvider] = useState(null)

  useEffect(() => {
    listCatalogModels()
      .then((d) => setRows(d.data))
      .finally(() => setLoading(false))
  }, [])

  const providers = useMemo(() => [...new Set(rows.map(r => r.provider))].sort(), [rows])

  const filtered = useMemo(() => rows.filter(r =>
    (!provider || r.provider === provider) &&
    (!q || r.id.toLowerCase().includes(q.toLowerCase()))
  ), [rows, q, provider])

  const MODE_META = { chat: { color: 'blue', label: '对话' }, embedding: { color: 'purple', label: '向量' }, image: { color: 'magenta', label: '图像' }, rerank: { color: 'cyan', label: '重排' }, audio: { color: 'gold', label: '音频' }, video: { color: 'red', label: '视频' } }
  const columns = [
    {
      title: '模型', dataIndex: 'id',
      render: (v, r) => (
        <Space>
          <Typography.Text strong>{v}</Typography.Text>
          {r.verified && <SafetyCertificateOutlined style={{ color: '#52c41a' }} title="Verified" />}
        </Space>
      ),
      sorter: (a, b) => a.id.localeCompare(b.id),
    },
    {
      title: '类型', dataIndex: 'mode',
      render: (m) => <Tag color={MODE_META[m]?.color}>{MODE_META[m]?.label || m}</Tag>,
      filters: [{ text: '对话', value: 'chat' }, { text: '向量', value: 'embedding' }, { text: '图像', value: 'image' }, { text: '重排', value: 'rerank' }, { text: '音频', value: 'audio' }, { text: '视频', value: 'video' }],
      onFilter: (val, r) => r.mode === val,
    },
    {
      title: '供应商', dataIndex: 'provider',
      render: p => <Tag color={PROVIDER_COLOR[p] || 'default'}>{p}</Tag>,
      filters: providers.map(p => ({ text: p, value: p })),
      onFilter: (val, r) => r.provider === val,
    },
    {
      title: '输入价 ($/1M)', dataIndex: 'input_price_per_1m',
      render: price, sorter: (a, b) => (a.input_price_per_1m ?? 0) - (b.input_price_per_1m ?? 0),
    },
    {
      title: '输出价 ($/1M)', dataIndex: 'output_price_per_1m',
      render: (v, r) => r.mode === 'image' ? `$${r.image_price}/张` : price(v),
      sorter: (a, b) => (a.output_price_per_1m ?? 0) - (b.output_price_per_1m ?? 0),
    },
    {
      title: '上下文窗口', dataIndex: 'context_window',
      render: v => v ? v.toLocaleString() : '—',
      sorter: (a, b) => (a.context_window ?? 0) - (b.context_window ?? 0),
    },
    {
      title: '能力', dataIndex: 'capabilities',
      render: caps => (caps || []).map(c => <Tag key={c}>{c}</Tag>),
    },
  ]

  return (
    <Card
      title={<Space><span>模型目录</span><Badge count={filtered.length} showZero color="#1677ff" overflowCount={9999} /></Space>}
      extra={
        <Space>
          <Select allowClear placeholder="按供应商筛选" style={{ width: 160 }} value={provider}
            onChange={setProvider} options={providers.map(p => ({ value: p, label: p }))} />
          <Input.Search placeholder="搜索模型名" allowClear style={{ width: 220 }}
            onChange={(e) => setQ(e.target.value)} />
        </Space>
      }
    >
      <Table columns={columns} dataSource={filtered} rowKey="id" loading={loading}
        size="small" pagination={{ pageSize: 20, showSizeChanger: true }} />
    </Card>
  )
}
