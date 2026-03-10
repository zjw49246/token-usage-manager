import { useEffect, useState } from 'react'
import { Button, Table, Tag, Space, Popconfirm, Progress, Tooltip, message, Typography } from 'antd'
import { PlusOutlined, EyeOutlined, DeleteOutlined, StopOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { listKeys, deleteKey, updateKey } from '../api/index.js'
import CreateKeyModal from '../components/CreateKeyModal.jsx'

function fmt(n) {
  if (!n && n !== 0) return '—'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n
}

function TokenProgress({ used, max }) {
  if (!max) return <Typography.Text type="secondary">{fmt(used)} / 不限</Typography.Text>
  const pct = Math.min(100, Math.round((used / max) * 100))
  return (
    <Tooltip title={`${fmt(used)} / ${fmt(max)}`}>
      <Progress percent={pct} size="small" status={pct >= 100 ? 'exception' : 'active'} />
    </Tooltip>
  )
}

export default function ApiKeys() {
  const [keys, setKeys] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const navigate = useNavigate()

  const load = async () => {
    setLoading(true)
    try {
      setKeys(await listKeys())
    } catch (e) {
      message.error('加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleToggle = async (record) => {
    await updateKey(record.id, { is_active: !record.is_active })
    message.success(record.is_active ? '已停用' : '已启用')
    load()
  }

  const handleDelete = async (id) => {
    await deleteKey(id)
    message.success('已删除')
    load()
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name', render: (v, r) => <a onClick={() => navigate(`/keys/${r.id}`)}>{v}</a> },
    { title: 'Key 前缀', dataIndex: 'key_prefix', key: 'key_prefix', render: v => <Typography.Text code>{v}...</Typography.Text> },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active',
      render: v => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>
    },
    {
      title: 'Token 用量', key: 'tokens',
      render: (_, r) => <TokenProgress used={r.usage?.total_tokens_used ?? 0} max={r.max_total_tokens} />
    },
    {
      title: '调用次数', key: 'calls',
      render: (_, r) => {
        const used = r.usage?.total_calls ?? 0
        return r.max_calls
          ? `${fmt(used)} / ${fmt(r.max_calls)}`
          : `${fmt(used)} / 不限`
      }
    },
    {
      title: '过期时间', dataIndex: 'valid_until', key: 'valid_until',
      render: v => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '不限'
    },
    {
      title: '操作', key: 'action',
      render: (_, r) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => navigate(`/keys/${r.id}`)}>详情</Button>
          <Button
            size="small"
            icon={r.is_active ? <StopOutlined /> : <PlayCircleOutlined />}
            onClick={() => handleToggle(r)}
          >
            {r.is_active ? '停用' : '启用'}
          </Button>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      )
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          创建 API Key
        </Button>
      </div>
      <Table columns={columns} dataSource={keys} rowKey="id" loading={loading} />
      <CreateKeyModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={() => { setModalOpen(false); load() }}
      />
    </div>
  )
}
