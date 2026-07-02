import { Layout as AntLayout, Menu, Typography, Select, Dropdown, Avatar, Space, Modal, Form, Input, message } from 'antd'
import {
  DashboardOutlined, KeyOutlined, CodeOutlined, SettingOutlined,
  TeamOutlined, UserOutlined, LogoutOutlined, DownOutlined,
  AppstoreOutlined, DollarOutlined, ClusterOutlined,
} from '@ant-design/icons'
import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore.js'
import { useI18n } from '../i18n.js'
import { createOrg, listOrgs } from '../api/index.js'

const { Sider, Header, Content } = AntLayout

const baseMenu = (t) => [
  { key: '/dashboard', icon: <DashboardOutlined />, label: t('nav.dashboard') },
  { key: '/keys', icon: <KeyOutlined />, label: t('nav.keys') },
  { key: '/models', icon: <AppstoreOutlined />, label: t('nav.models') },
  { key: '/billing', icon: <DollarOutlined />, label: t('nav.billing') },
  { key: '/members', icon: <TeamOutlined />, label: t('nav.members') },
  { key: '/integration', icon: <CodeOutlined />, label: t('nav.integration') },
  { key: '/settings', icon: <SettingOutlined />, label: t('nav.settings') },
]

export default function Layout({ children }) {
  const navigate = useNavigate()
  const location = useLocation()
  const selectedKey = '/' + location.pathname.split('/')[1]
  const { user, orgs, currentOrgId, setCurrentOrg, setOrgs, logout } = useAuthStore()
  const { lang, setLang, t } = useI18n()
  const [newOrgOpen, setNewOrgOpen] = useState(false)
  const [form] = Form.useForm()
  const menuItems = user?.is_superadmin
    ? [...baseMenu(t), { key: '/channels', icon: <ClusterOutlined />, label: t('nav.channels') }]
    : baseMenu(t)

  const onCreateOrg = async () => {
    const values = await form.validateFields()
    try {
      await createOrg(values)
      const fresh = await listOrgs()
      setOrgs(fresh)
      const created = fresh.find((o) => o.name === values.name)
      if (created) setCurrentOrg(created.id)
      setNewOrgOpen(false); form.resetFields()
      message.success('组织已创建')
    } catch (e) { message.error(e.response?.data?.detail || '创建失败') }
  }

  const orgOptions = [
    ...orgs.map((o) => ({ value: o.id, label: `${o.name} · ${o.role}` })),
    { value: '__new__', label: t('header.newOrg') },
  ]

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider theme="dark" width={200}>
        <div style={{ padding: '20px 24px 16px', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
          <Typography.Text strong style={{ color: '#fff', fontSize: 15 }}>TokenRouter</Typography.Text>
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[selectedKey]} items={menuItems}
          onClick={({ key }) => navigate(key)} style={{ marginTop: 8 }} />
      </Sider>
      <AntLayout>
        <Header style={{ background: '#fff', padding: '0 24px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Space size="middle">
            <Typography.Text type="secondary">{t('header.org')}</Typography.Text>
            <Select
              value={currentOrgId}
              style={{ minWidth: 220 }}
              options={orgOptions}
              onChange={(v) => v === '__new__' ? setNewOrgOpen(true) : setCurrentOrg(v)}
            />
          </Space>
          <Space size="large">
            <Select
              size="small" value={lang} onChange={setLang} style={{ width: 96 }}
              options={[{ value: 'zh', label: '中文' }, { value: 'en', label: 'English' }]}
            />
          <Dropdown menu={{ items: [
            { key: 'email', label: user?.email, disabled: true },
            { type: 'divider' },
            { key: 'logout', icon: <LogoutOutlined />, label: t('header.logout'), onClick: () => { logout(); navigate('/') } },
          ] }}>
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span>{user?.name}</span>
              <DownOutlined style={{ fontSize: 10 }} />
            </Space>
          </Dropdown>
          </Space>
        </Header>
        <Content style={{ margin: 24, minHeight: 280 }}>{children}</Content>
      </AntLayout>

      <Modal title={t('header.createOrg')} open={newOrgOpen} onOk={onCreateOrg} onCancel={() => setNewOrgOpen(false)} okText={t('common.create')}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label={t('header.orgName')} rules={[{ required: true }]}>
            <Input placeholder="Acme Inc." />
          </Form.Item>
        </Form>
      </Modal>
    </AntLayout>
  )
}
