import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Row, Col, Descriptions, Tag, Progress, Table, Button,
  Form, InputNumber, Select, DatePicker, Switch, message, Tooltip, Spin, Space, Typography
} from 'antd'
import { ArrowLeftOutlined, EditOutlined, SaveOutlined, CloseOutlined } from '@ant-design/icons'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer
} from 'recharts'
import dayjs from 'dayjs'
import { getKey, updateKey, getKeyUsage, getTrend } from '../api/index.js'

const MODELS = ['gemini-2.5-pro-preview-05-06', 'gemini-2.5-flash-preview-04-17', 'gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-1.5-pro', 'gemini-1.5-flash']

function fmt(n) {
  if (!n && n !== 0) return '—'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n
}

export default function KeyDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [keyData, setKeyData] = useState(null)
  const [editing, setEditing] = useState(false)
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [usage, setUsage] = useState({ items: [], total: 0 })
  const [page, setPage] = useState(1)
  const [trend, setTrend] = useState([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const [kd, us, tr] = await Promise.all([
        getKey(id),
        getKeyUsage(id, { page, page_size: 10 }),
        getTrend({ granularity: 'day', days: 7 }),
      ])
      setKeyData(kd)
      setUsage(us)
      setTrend(tr.points)
    } catch (e) {
      message.error('加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [id, page])

  const startEdit = () => {
    form.setFieldsValue({
      name: keyData.name,
      is_active: keyData.is_active,
      allowed_models: keyData.allowed_models || [],
      max_total_tokens: keyData.max_total_tokens,
      max_calls: keyData.max_calls,
      max_rpm: keyData.max_rpm,
      time_range: keyData.valid_from && keyData.valid_until
        ? [dayjs(keyData.valid_from), dayjs(keyData.valid_until)] : null,
    })
    setEditing(true)
  }

  const save = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await updateKey(id, {
        name: values.name,
        is_active: values.is_active,
        allowed_models: values.allowed_models?.length ? values.allowed_models : null,
        max_total_tokens: values.max_total_tokens || null,
        max_calls: values.max_calls || null,
        max_rpm: values.max_rpm || null,
        valid_from: values.time_range?.[0]?.toISOString() || null,
        valid_until: values.time_range?.[1]?.toISOString() || null,
      })
      message.success('已保存')
      setEditing(false)
      load()
    } catch (e) {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (loading && !keyData) return <Spin style={{ display: 'block', margin: '80px auto' }} />

  const usedTokens = keyData?.usage?.total_tokens_used ?? 0
  const usedCalls = keyData?.usage?.total_calls ?? 0

  const usageColumns = [
    { title: '时间', dataIndex: 'created_at', render: v => dayjs(v).format('MM-DD HH:mm:ss') },
    { title: '模型', dataIndex: 'model' },
    { title: '输入', dataIndex: 'input_tokens', render: fmt },
    { title: '输出', dataIndex: 'output_tokens', render: fmt },
    { title: '合计', dataIndex: 'total_tokens', render: fmt },
    { title: '耗时', dataIndex: 'duration_ms', render: v => v ? `${v}ms` : '—' },
    { title: '状态', dataIndex: 'status', render: v => <Tag color={v === 'success' ? 'green' : 'red'}>{v}</Tag> },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/keys')}>返回</Button>
        {!editing
          ? <Button icon={<EditOutlined />} onClick={startEdit}>编辑配置</Button>
          : <>
              <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={save}>保存</Button>
              <Button icon={<CloseOutlined />} onClick={() => setEditing(false)}>取消</Button>
            </>
        }
      </Space>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="基本配置">
            {editing ? (
              <Form form={form} layout="vertical">
                <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                  <Select.Search placeholder="名称" />
                </Form.Item>
                <Form.Item name="is_active" label="状态" valuePropName="checked">
                  <Switch checkedChildren="启用" unCheckedChildren="停用" />
                </Form.Item>
                <Form.Item name="allowed_models" label="允许模型（留空不限）">
                  <Select mode="multiple" allowClear options={MODELS.map(m => ({ value: m, label: m }))} />
                </Form.Item>
                <Form.Item name="max_total_tokens" label="Token 总上限">
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="max_calls" label="调用次数上限">
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="max_rpm" label="RPM 上限">
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="time_range" label="生效时间区间">
                  <DatePicker.RangePicker showTime style={{ width: '100%' }} />
                </Form.Item>
              </Form>
            ) : (
              <Descriptions column={1} size="small">
                <Descriptions.Item label="名称">{keyData?.name}</Descriptions.Item>
                <Descriptions.Item label="Key 前缀"><Typography.Text code>{keyData?.key_prefix}...</Typography.Text></Descriptions.Item>
                <Descriptions.Item label="状态"><Tag color={keyData?.is_active ? 'green' : 'default'}>{keyData?.is_active ? '启用' : '停用'}</Tag></Descriptions.Item>
                <Descriptions.Item label="允许模型">{keyData?.allowed_models?.join(', ') || '不限'}</Descriptions.Item>
                <Descriptions.Item label="Token 上限">{fmt(keyData?.max_total_tokens) || '不限'}</Descriptions.Item>
                <Descriptions.Item label="调用次数上限">{fmt(keyData?.max_calls) || '不限'}</Descriptions.Item>
                <Descriptions.Item label="RPM">{keyData?.max_rpm || '不限'}</Descriptions.Item>
                <Descriptions.Item label="生效时间">{keyData?.valid_from ? dayjs(keyData.valid_from).format('YYYY-MM-DD HH:mm') : '不限'}</Descriptions.Item>
                <Descriptions.Item label="过期时间">{keyData?.valid_until ? dayjs(keyData.valid_until).format('YYYY-MM-DD HH:mm') : '不限'}</Descriptions.Item>
                <Descriptions.Item label="创建时间">{dayjs(keyData?.created_at).format('YYYY-MM-DD HH:mm')}</Descriptions.Item>
              </Descriptions>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="用量统计">
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 4 }}>Token 用量</div>
              {keyData?.max_total_tokens
                ? <Progress percent={Math.min(100, Math.round(usedTokens / keyData.max_total_tokens * 100))} format={() => `${fmt(usedTokens)} / ${fmt(keyData.max_total_tokens)}`} />
                : <Typography.Text>{fmt(usedTokens)} / 不限</Typography.Text>
              }
            </div>
            <div>
              <div style={{ marginBottom: 4 }}>调用次数</div>
              {keyData?.max_calls
                ? <Progress percent={Math.min(100, Math.round(usedCalls / keyData.max_calls * 100))} format={() => `${usedCalls} / ${keyData.max_calls}`} />
                : <Typography.Text>{usedCalls} / 不限</Typography.Text>
              }
            </div>
          </Card>

          <Card title="近 7 天趋势" style={{ marginTop: 16 }}>
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={trend}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="time" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={fmt} tick={{ fontSize: 11 }} />
                <ReTooltip formatter={fmt} />
                <Line type="monotone" dataKey="tokens" name="Tokens" stroke="#1677ff" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      <Card title="调用明细" style={{ marginTop: 16 }}>
        <Table
          columns={usageColumns}
          dataSource={usage.items}
          rowKey="id"
          loading={loading}
          pagination={{ current: page, pageSize: 10, total: usage.total, onChange: setPage }}
          size="small"
        />
      </Card>
    </div>
  )
}
