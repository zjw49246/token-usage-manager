import { useEffect, useState } from 'react'
import { Card, Form, Input, Button, Tabs, Typography, message, Divider, Space } from 'antd'
import { GithubOutlined, GoogleOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { login, register, fetchMe, listOrgs, oauthProviders, oauthUrl } from '../api/index.js'
import { useAuthStore } from '../stores/authStore.js'

const PROVIDER_META = {
  github: { icon: <GithubOutlined />, label: 'GitHub' },
  google: { icon: <GoogleOutlined />, label: 'Google' },
}

export default function Login() {
  const [tab, setTab] = useState('login')
  const [loading, setLoading] = useState(false)
  const [providers, setProviders] = useState([])
  const navigate = useNavigate()
  const { setTokens, setUser, setOrgs } = useAuthStore()

  useEffect(() => { oauthProviders().then((d) => setProviders(d.providers)).catch(() => {}) }, [])

  const onOAuth = async (provider) => {
    try {
      const redirect_uri = window.location.origin + '/oauth/callback'
      const { authorize_url, state } = await oauthUrl(provider, redirect_uri)
      sessionStorage.setItem('oauth_provider', provider)
      sessionStorage.setItem('oauth_state', state)
      window.location.href = authorize_url
    } catch (e) { message.error('第三方登录未配置') }
  }

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
        {providers.length > 0 && (
          <>
            <Divider plain style={{ color: '#aaa' }}>或</Divider>
            <Space direction="vertical" style={{ width: '100%' }}>
              {providers.map((p) => (
                <Button key={p} block size="large" icon={PROVIDER_META[p]?.icon} onClick={() => onOAuth(p)}>
                  用 {PROVIDER_META[p]?.label || p} 登录
                </Button>
              ))}
            </Space>
          </>
        )}
      </Card>
    </div>
  )
}
