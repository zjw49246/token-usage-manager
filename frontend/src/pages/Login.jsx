import { useEffect, useState } from 'react'
import { Card, Form, Input, Button, Tabs, Typography, message, Divider, Space } from 'antd'
import { GithubOutlined, GoogleOutlined, MessageOutlined, LoginOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { login, register, fetchMe, listOrgs, oauthProviders, oauthUrl } from '../api/index.js'
import { useAuthStore } from '../stores/authStore.js'
import { useI18n } from '../i18n.js'

const PROVIDER_META = {
  github: { icon: <GithubOutlined />, label: 'GitHub' },
  google: { icon: <GoogleOutlined />, label: 'Google' },
  discord: { icon: <MessageOutlined />, label: 'Discord' },
  oidc: { icon: <LoginOutlined />, label: 'SSO' },
}

export default function Login() {
  const [tab, setTab] = useState('login')
  const [loading, setLoading] = useState(false)
  const [providers, setProviders] = useState([])
  const navigate = useNavigate()
  const { setTokens, setUser, setOrgs } = useAuthStore()
  const { lang, setLang, t } = useI18n()

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
      message.success(t('auth.registerOk'))
    } catch (e) {
      message.error(e.response?.data?.detail || '注册失败')
    } finally { setLoading(false) }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f0f2f5' }}>
      <Card style={{ width: 400 }}>
        <div style={{ textAlign: 'center', marginBottom: 8 }}>
          <Typography.Title level={3} style={{ marginBottom: 0 }}>TokenRouter</Typography.Title>
          <Typography.Text type="secondary">{t('app.subtitle')}</Typography.Text>
        </div>
        <div style={{ textAlign: 'right', marginBottom: 8 }}>
          <Button type="link" size="small" onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}>
            {lang === 'zh' ? 'English' : '中文'}
          </Button>
        </div>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          centered
          items={[
            {
              key: 'login', label: t('auth.login'),
              children: (
                <Form layout="vertical" onFinish={onLogin}>
                  <Form.Item name="email" label={t('auth.email')} rules={[{ required: true, type: 'email' }]}>
                    <Input placeholder="you@example.com" size="large" />
                  </Form.Item>
                  <Form.Item name="password" label={t('auth.password')} rules={[{ required: true }]}>
                    <Input.Password placeholder={t('auth.password')} size="large" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block size="large" loading={loading}>{t('auth.login')}</Button>
                </Form>
              ),
            },
            {
              key: 'register', label: t('auth.register'),
              children: (
                <Form layout="vertical" onFinish={onRegister}>
                  <Form.Item name="name" label={t('auth.name')} rules={[{ required: true }]}>
                    <Input placeholder={t('auth.name')} size="large" />
                  </Form.Item>
                  <Form.Item name="email" label={t('auth.email')} rules={[{ required: true, type: 'email' }]}>
                    <Input placeholder="you@example.com" size="large" />
                  </Form.Item>
                  <Form.Item name="password" label={t('auth.password')} rules={[{ required: true, min: 8, message: '≥ 8' }]}>
                    <Input.Password placeholder="≥ 8" size="large" />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block size="large" loading={loading}>{t('auth.register')}</Button>
                </Form>
              ),
            },
          ]}
        />
        {providers.length > 0 && (
          <>
            <Divider plain style={{ color: '#aaa' }}>{t('auth.or')}</Divider>
            <Space direction="vertical" style={{ width: '100%' }}>
              {providers.map((p) => (
                <Button key={p} block size="large" icon={PROVIDER_META[p]?.icon} onClick={() => onOAuth(p)}>
                  {t('auth.loginWith', { p: PROVIDER_META[p]?.label || p })}
                </Button>
              ))}
            </Space>
          </>
        )}
      </Card>
    </div>
  )
}
