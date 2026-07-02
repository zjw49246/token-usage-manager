import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Spin } from 'antd'
import Layout from './components/Layout.jsx'
import Login from './pages/Login.jsx'
import OAuthCallback from './pages/OAuthCallback.jsx'
import Dashboard from './pages/Dashboard.jsx'
import ApiKeys from './pages/ApiKeys.jsx'
import KeyDetail from './pages/KeyDetail.jsx'
import Models from './pages/Models.jsx'
import Channels from './pages/Channels.jsx'
import Billing from './pages/Billing.jsx'
import Members from './pages/Members.jsx'
import Integration from './pages/Integration.jsx'
import Settings from './pages/Settings.jsx'
import { useAuthStore } from './stores/authStore.js'
import { fetchMe, listOrgs } from './api/index.js'

export default function App() {
  const { accessToken, user, setUser, setOrgs, logout } = useAuthStore()
  const [booting, setBooting] = useState(!!accessToken)

  // 刷新页面后用已存的 token 恢复会话
  useEffect(() => {
    if (accessToken && !user) {
      Promise.all([fetchMe(), listOrgs()])
        .then(([me, orgs]) => { setUser(me); setOrgs(orgs) })
        .catch(() => logout())
        .finally(() => setBooting(false))
    } else {
      setBooting(false)
    }
  }, [])

  if (!accessToken) {
    return (
      <Routes>
        <Route path="/oauth/callback" element={<OAuthCallback />} />
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }

  if (booting) {
    return <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}><Spin size="large" /></div>
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/keys" element={<ApiKeys />} />
        <Route path="/keys/:id" element={<KeyDetail />} />
        <Route path="/models" element={<Models />} />
        <Route path="/channels" element={<Channels />} />
        <Route path="/billing" element={<Billing />} />
        <Route path="/members" element={<Members />} />
        <Route path="/integration" element={<Integration />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Layout>
  )
}
