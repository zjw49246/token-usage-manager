import { Layout as AntLayout, Menu, Typography, Select, Dropdown, Avatar, Space, Modal, Form, Input, message } from 'antd'
import {
  DashboardOutlined, KeyOutlined, CodeOutlined, SettingOutlined,
  TeamOutlined, UserOutlined, LogoutOutlined, DownOutlined,
  AppstoreOutlined, DollarOutlined, ClusterOutlined,
} from '@ant-design/icons'
import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore.js'
import { createOrg, listOrgs } from '../api/index.js'

const { Sider, Header, Content } = AntLayout

const baseMenu = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '总览' },
  { key: '/keys', icon: <KeyOutlined />, label: 'API Keys' },
  { key: '/models', icon: <AppstoreOutlined />, label: '模型目录' },
  { key: '/billing', icon: <DollarOutlined />, label: '额度计费' },
  { key: '/members', icon: <TeamOutlined />, label: '成员' },
  { key: '/integration', icon: <CodeOutlined />, label: '接入指南' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
]
const superadminMenu = { key: '/channels', icon: <ClusterOutlined />, label: '通道 (超管)' }

export default function Layout({ children }) {
  const navigate = useNavigate()
  const location = useLocation()
  const selectedKey = '/' + location.pathname.split('/')[1]
  const { user, orgs, currentOrgId, setCurrentOrg, setOrgs, logout } = useAuthStore()
  const [newOrgOpen, setNewOrgOpen] = useState(false)
  const [form] = Form.useForm()
  const menuItems = user?.is_superadmin ? [...baseMenu, superadminMenu] : baseMenu

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
    { value: '__new__', label: '＋ 新建组织' },
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
            <Typography.Text type="secondary">组织</Typography.Text>
            <Select
              value={currentOrgId}
              style={{ minWidth: 220 }}
              options={orgOptions}
              onChange={(v) => v === '__new__' ? setNewOrgOpen(true) : setCurrentOrg(v)}
            />
          </Space>
          <Dropdown menu={{ items: [
            { key: 'email', label: user?.email, disabled: true },
            { type: 'divider' },
            { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: () => { logout(); navigate('/') } },
          ] }}>
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span>{user?.name}</span>
              <DownOutlined style={{ fontSize: 10 }} />
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ margin: 24, minHeight: 280 }}>{children}</Content>
      </AntLayout>

      <Modal title="新建组织" open={newOrgOpen} onOk={onCreateOrg} onCancel={() => setNewOrgOpen(false)} okText="创建">
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="组织名称" rules={[{ required: true }]}>
            <Input placeholder="如：Acme Inc." />
          </Form.Item>
        </Form>
      </Modal>
    </AntLayout>
  )
}
