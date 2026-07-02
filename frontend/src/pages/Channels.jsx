import { useEffect, useState } from 'react'
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, InputNumber, Select, Switch,
  Popconfirm, message, Alert, Typography,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import {
  listChannels, listChannelProviders, createChannel, updateChannel, deleteChannel, listCatalogModels,
} from '../api/index.js'
import { useAuthStore } from '../stores/authStore.js'

export default function Channels() {
  const isSuperadmin = useAuthStore((s) => s.user?.is_superadmin)
  const [rows, setRows] = useState([])
  const [providers, setProviders] = useState([])
  const [models, setModels] = useState([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const [ch, pv, md] = await Promise.all([listChannels(), listChannelProviders(), listCatalogModels()])
      setRows(ch)
      setProviders(pv.map((p) => ({ value: p.id, label: `${p.name} (${p.litellm_prefix})` })))
      setModels(md.data.map((m) => ({ value: m.id, label: `${m.id} · ${m.provider}` })))
    } catch (e) {
      if (e.response?.status !== 403) message.error('加载失败')
    } finally { setLoading(false) }
  }
  useEffect(() => { if (isSuperadmin) load() }, [isSuperadmin])

  if (!isSuperadmin) {
    return <Alert type="warning" showIcon message="通道管理仅限平台超管"
      description="用 ADMIN_TOKEN 调 POST /admin/superadmin {email} 可把账号提升为超管。" />
  }

  const openCreate = () => { setEditing(null); form.resetFields(); form.setFieldsValue({ weight: 1, priority: 0, enabled: true }); setOpen(true) }
  const openEdit = (r) => {
    setEditing(r)
    form.setFieldsValue({ ...r, api_key: undefined, model_map: r.model_map ? JSON.stringify(r.model_map) : '' })
    setOpen(true)
  }

  const submit = async () => {
    const v = await form.validateFields()
    let model_map = null
    if (v.model_map) { try { model_map = JSON.parse(v.model_map) } catch { return message.error('model_map 不是合法 JSON') } }
    const payload = { ...v, model_map }
    if (!payload.api_key) delete payload.api_key  // 空则不改
    try {
      if (editing) await updateChannel(editing.id, payload)
      else await createChannel(payload)
      message.success('已保存'); setOpen(false); load()
    } catch (e) { message.error(e.response?.data?.detail || '保存失败') }
  }

  const remove = async (id) => { await deleteChannel(id); message.success('已删除'); load() }

  const columns = [
    { title: '名称', dataIndex: 'name' },
    { title: '供应商', dataIndex: 'provider_id', render: (id) => providers.find(p => p.value === id)?.label || id },
    { title: '服务模型', dataIndex: 'models', render: (m) => (m || []).length ? <Tag>{(m || []).length} 个</Tag> : <Tag color="red">未配置</Tag> },
    { title: '权重', dataIndex: 'weight' },
    { title: '优先级', dataIndex: 'priority' },
    { title: '凭证', dataIndex: 'has_key', render: (v) => v ? <Tag color="green">独立</Tag> : <Tag>用供应商 env</Tag> },
    { title: 'API Base', dataIndex: 'api_base', render: (v) => v || '默认' },
    { title: '状态', dataIndex: 'enabled', render: (v) => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag> },
    {
      title: '操作', render: (_, r) => (
        <Space>
          <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
          <Popconfirm title="删除该通道？" onConfirm={() => remove(r.id)}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="上游通道（负载均衡 / 故障转移）"
      extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建通道</Button>}
    >
      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="同一模型可配多条通道：按优先级分层、层内按权重加权随机；某条失败自动转下一条（max_retries 控制次数）。" />
      <Table columns={columns} dataSource={rows} rowKey="id" loading={loading} size="small" />

      <Modal title={editing ? '编辑通道' : '新建通道'} open={open} onOk={submit} onCancel={() => setOpen(false)} okText="保存" width={560}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input placeholder="如：OpenAI 主通道" /></Form.Item>
          <Form.Item name="provider_id" label="供应商" rules={[{ required: true }]}>
            <Select options={providers} disabled={!!editing} />
          </Form.Item>
          <Form.Item name="api_key" label={editing ? '上游凭证（留空=不修改）' : '上游凭证（留空=用供应商 env）'}>
            <Input.Password placeholder="sk-..." autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="api_base" label="API Base 覆盖（可选）"><Input placeholder="https://..." /></Form.Item>
          <Form.Item name="models" label="服务的模型" rules={[{ required: true, message: '至少选一个' }]}>
            <Select mode="multiple" showSearch optionFilterProp="label" options={models} placeholder="该通道能服务哪些模型" />
          </Form.Item>
          <Form.Item name="model_map" label="模型名映射 model_map（可选 JSON）"
            tooltip='{"公开名":"上游litellm全名"}，不填则用目录默认'>
            <Input.TextArea rows={2} placeholder='{"gpt-4o":"azure/gpt-4o"}' />
          </Form.Item>
          <Space size="large">
            <Form.Item name="weight" label="权重" rules={[{ required: true }]}><InputNumber min={1} /></Form.Item>
            <Form.Item name="priority" label="优先级（高者先试）" rules={[{ required: true }]}><InputNumber /></Form.Item>
            <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
          </Space>
        </Form>
      </Modal>
    </Card>
  )
}
