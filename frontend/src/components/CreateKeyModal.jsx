import { useState } from 'react'
import {
  Modal, Form, Input, InputNumber, Select, DatePicker, Alert, Typography, Space, Button, message
} from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { createKey } from '../api/index.js'

const MODELS = [
  'gemini-2.5-pro-preview-05-06',
  'gemini-2.5-flash-preview-04-17',
  'gemini-2.0-flash',
  'gemini-2.0-flash-lite',
  'gemini-1.5-pro',
  'gemini-1.5-flash',
]

export default function CreateKeyModal({ open, onClose, onCreated }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [createdKey, setCreatedKey] = useState(null)

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
        valid_from: values.time_range?.[0]?.toISOString() || null,
        valid_until: values.time_range?.[1]?.toISOString() || null,
      }
      const data = await createKey(payload)
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
    navigator.clipboard.writeText(createdKey)
    message.success('已复制到剪贴板')
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
            <Select mode="multiple" allowClear options={MODELS.map(m => ({ value: m, label: m }))} placeholder="留空表示不限制" />
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
          <Form.Item name="time_range" label="生效时间区间（留空 = 不限）">
            <DatePicker.RangePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      )}
    </Modal>
  )
}
