import { useState } from 'react'
import { Card, Form, Input, Button, Tabs, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { login, register, fetchMe, listOrgs } from '../api/index.js'
import { useAuthStore } from '../stores/authStore.js'

export default function Login() {
  const [tab, setTab] = useState('login')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { setTokens, setUser, setOrgs } = useAuthStore()

  const bootstrap = async (tokens) => {
    setTokens(tokens)
    const [me, orgs] = await Promise.all([fetchMe(), listOrgs()])
    setUser(me)
    setOrgs(orgs)
    navigate('/dashboard')
  }

  const onLogin = async (values) => {
    setLoading(true)
    try {
      await bootstrap(await login(values))
    } catch (e) {
      message.error(e.response?.data?.detail || '登录失败')
    } finally { setLoading(false) }
  }

  const onRegister = async (values) => {
    setLoading(true)
    try {
      await bootstrap(await register(values))
      message.success('注册成功，已为你创建个人组织')
    } catch (e) {
      message.error(e.response?.data?.detail || '注册失败')
    } finally { setLoading(false) }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f0f2f5' }}>
      <Card style={{ width: 400 }}>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <Typography.Title level={3} style={{ marginBottom: 0 }}>TokenRouter</Typography.Title>
          <Typography.Text type="secondary">统一多供应商 AI 模型网关</Typography.Text>
        </div>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          centered
          items={[
            {
              key: 'login', label: '登录',
              children: (
                <Form layout="vertical" onFinish={onLogin}>
                  <Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email' }]}>
                    <Input placeholder="you@example.com" size="large" />
                  </Form.Item>
                  <Form.Item name="password" label="密码" rules={[{ required: true }]}>
                    <Input.Password placeholder="密码" size="large" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block size="large" loading={loading}>登录</Button>
                </Form>
              ),
            },
            {
              key: 'register', label: '注册',
              children: (
                <Form layout="vertical" onFinish={onRegister}>
                  <Form.Item name="name" label="姓名" rules={[{ required: true }]}>
                    <Input placeholder="你的名字" size="large" />
                  </Form.Item>
                  <Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email' }]}>
                    <Input placeholder="you@example.com" size="large" />
                  </Form.Item>
                  <Form.Item name="password" label="密码" rules={[{ required: true, min: 8, message: '至少 8 位' }]}>
                    <Input.Password placeholder="至少 8 位" size="large" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block size="large" loading={loading}>注册</Button>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}
