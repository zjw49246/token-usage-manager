import { useState } from 'react'
import { Card, Form, Input, Button, message, Typography, Divider, Alert } from 'antd'
import { useAdminStore } from '../stores/adminStore.js'

export default function Settings() {
  const { token, setToken } = useAdminStore()
  const [form] = Form.useForm()
  const [saved, setSaved] = useState(false)

  const handleSave = async () => {
    const values = await form.validateFields()
    setToken(values.admin_token)
    setSaved(true)
    message.success('Admin Token 已更新，页面将刷新')
    setTimeout(() => window.location.reload(), 1000)
  }

  const maskedToken = token ? token.slice(0, 6) + '••••••••••••••••' : ''

  return (
    <div style={{ maxWidth: 600 }}>
      <Card title="Admin Token 配置">
        <Alert
          type="info"
          message="Admin Token 存储在浏览器 localStorage，用于所有管理 API 的鉴权。"
          style={{ marginBottom: 16 }}
        />
        <Typography.Text type="secondary">当前 Token：{maskedToken || '未设置'}</Typography.Text>
        <Divider />
        <Form form={form} layout="vertical" initialValues={{ admin_token: token }}>
          <Form.Item
            name="admin_token"
            label="Admin Token"
            rules={[{ required: true, message: '请输入 Token' }]}
          >
            <Input.Password placeholder="输入新的 Admin Token" />
          </Form.Item>
          <Button type="primary" onClick={handleSave}>保存</Button>
        </Form>
      </Card>

      <Card title="服务信息" style={{ marginTop: 16 }}>
        <Typography.Paragraph>
          <strong>代理接口地址：</strong><Typography.Text code>{window.location.origin}/v1</Typography.Text>
        </Typography.Paragraph>
        <Typography.Paragraph>
          <strong>使用方式：</strong>将客户端 SDK 的 <Typography.Text code>base_url</Typography.Text> 设为上方地址，
          <Typography.Text code>api_key</Typography.Text> 填入 API Keys 页面分配的 Key，即可透明调用 Gemini API。
        </Typography.Paragraph>
        <Typography.Paragraph>
          <strong>API 文档：</strong><a href="/api/docs" target="_blank">/api/docs</a>
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
