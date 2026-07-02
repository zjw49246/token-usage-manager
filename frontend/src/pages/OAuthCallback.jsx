import { useEffect, useState } from 'react'
import { Spin, Result, Button } from 'antd'
import { useNavigate } from 'react-router-dom'
import { oauthExchange, fetchMe, listOrgs } from '../api/index.js'
import { useAuthStore } from '../stores/authStore.js'

export default function OAuthCallback() {
  const navigate = useNavigate()
  const { setTokens, setUser, setOrgs } = useAuthStore()
  const [error, setError] = useState(null)

  useEffect(() => {
    const run = async () => {
      const params = new URLSearchParams(window.location.search)
      const code = params.get('code')
      const state = params.get('state')
      const provider = sessionStorage.getItem('oauth_provider')
      const savedState = sessionStorage.getItem('oauth_state')
      if (!code || !provider) { setError('缺少授权信息'); return }
      if (savedState && state && savedState !== state) { setError('state 校验失败（可能的 CSRF）'); return }
      try {
        const tokens = await oauthExchange(provider, { code, redirect_uri: window.location.origin + '/oauth/callback' })
        setTokens(tokens)
        const [me, orgs] = await Promise.all([fetchMe(), listOrgs()])
        setUser(me); setOrgs(orgs)
        sessionStorage.removeItem('oauth_provider'); sessionStorage.removeItem('oauth_state')
        navigate('/dashboard', { replace: true })
      } catch (e) {
        setError(e.response?.data?.detail || '登录失败')
      }
    }
    run()
  }, [])

  if (error) {
    return <Result status="error" title="第三方登录失败" subTitle={error}
      extra={<Button type="primary" onClick={() => navigate('/')}>返回登录</Button>} />
  }
  return <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}><Spin size="large" tip="登录中…" /></div>
}
