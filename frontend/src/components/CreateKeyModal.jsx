import { useEffect, useState } from 'react'
import {
  Modal, Form, Input, InputNumber, Select, DatePicker, Alert, Typography, Space, Button, message
} from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { createKey, listCatalogModels } from '../api/index.js'

export default function CreateKeyModal({ orgId, open, onClose, onCreated }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [createdKey, setCreatedKey] = useState(null)
  const [models, setModels] = useState([])

  useEffect(() => {
    if (open) {
      listCatalogModels()
        .then((d) => setModels(d.data.map((m) => ({ value: m.id, label: `${m.id}  ·  ${m.provider}` }))))
        .catch(() => setModels([]))
    }
  }, [open])

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      const payload = {
        name: values.name,
        allowed_models: values.allowed_models?.length ? values.allowed_models : null,
        max_total_tokens: values.max_total_tokens || null,
        max_calls: values.max_calls || null,
        max_rpm: values.max_rpm || null,
        max_cost_usd: values.max_cost_usd || null,
        allowed_ips: values.allowed_ips?.length ? values.allowed_ips : null,
        valid_from: values.time_range?.[0]?.toISOString() || null,
        valid_until: values.time_range?.[1]?.toISOString() || null,
      }
      const data = await createKey(orgId, payload)
      setCreatedKey(data.key)
      onCreated?.()
    } catch (e) {
      message.error('创建失败：' + (e.response?.data?.detail || e.message))
    } finally {
      setLoading(false)
    }
  }

  const handleClose = () => {
    form.resetFields()
    setCreatedKey(null)
    onClose()
  }

  const copyKey = () => {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(createdKey).then(
        () => message.success('已复制到剪贴板'),
        () => fallbackCopy(),
      )
    } else {
      fallbackCopy()
    }
  }

  const fallbackCopy = () => {
    const textarea = document.createElement('textarea')
    textarea.value = createdKey
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    try {
      document.execCommand('copy')
      message.success('已复制到剪贴板')
    } catch {
      message.error('复制失败，请手动选中复制')
    }
    document.body.removeChild(textarea)
  }

  return (
    <Modal
      title={createdKey ? '创建成功' : '创建 API Key'}
      open={open}
      onCancel={handleClose}
      footer={createdKey
        ? <Button type="primary" onClick={handleClose}>完成</Button>
        : [
            <Button key="cancel" onClick={handleClose}>取消</Button>,
            <Button key="submit" type="primary" loading={loading} onClick={handleSubmit}>创建</Button>,
          ]
      }
      width={520}
    >
      {createdKey ? (
        <div>
          <Alert
            type="warning"
            message="请立即复制此 Key，关闭后将无法再次查看"
            style={{ marginBottom: 16 }}
          />
          <Space.Compact style={{ width: '100%' }}>
            <Input value={createdKey} readOnly style={{ fontFamily: 'monospace' }} />
            <Button icon={<CopyOutlined />} onClick={copyKey}>复制</Button>
          </Space.Compact>
        </div>
      ) : (
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：App A 生产环境" />
          </Form.Item>
          <Form.Item name="allowed_models" label="允许使用的模型（留空 = 不限）">
            <Select mode="multiple" allowClear showSearch optionFilterProp="label"
              options={models} placeholder="留空表示不限制；支持搜索" />
          </Form.Item>
          <Form.Item name="max_total_tokens" label="Token 总上限（留空 = 不限）">
            <InputNumber min={1} style={{ width: '100%' }} placeholder="如：1000000" />
          </Form.Item>
          <Form.Item name="max_calls" label="调用次数上限（留空 = 不限）">
            <InputNumber min={1} style={{ width: '100%' }} placeholder="如：1000" />
          </Form.Item>
          <Form.Item name="max_rpm" label="每分钟请求数 RPM（留空 = 不限）">
            <InputNumber min={1} style={{ width: '100%' }} placeholder="如：60" />
          </Form.Item>
          <Form.Item name="max_cost_usd" label="成本上限 USD（留空 = 不限）">
            <InputNumber min={0.01} step={1} style={{ width: '100%' }} placeholder="如：10" prefix="$" />
          </Form.Item>
          <Form.Item name="allowed_ips" label="IP 白名单（留空 = 不限，支持 CIDR）">
            <Select mode="tags" allowClear placeholder="如 1.2.3.4 或 10.0.0.0/8，回车添加" tokenSeparators={[',', ' ']} />
          </Form.Item>
          <Form.Item name="time_range" label="生效时间区间（留空 = 不限）">
            <DatePicker.RangePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      )}
    </Modal>
  )
}
