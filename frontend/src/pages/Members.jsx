import { useEffect, useState } from 'react'
import { Table, Tag, Button, Space, Modal, Form, Input, InputNumber, Select, Popconfirm, message } from 'antd'
import { UserAddOutlined } from '@ant-design/icons'
import { listMembers, addMember, updateMemberRole, removeMember } from '../api/index.js'
import { useAuthStore } from '../stores/authStore.js'

const ROLE_COLOR = { owner: 'gold', admin: 'blue', member: 'default' }

export default function Members() {
  const { currentOrgId, currentOrg, user } = useAuthStore()
  const org = currentOrg()
  const myRole = org?.role
  const canManage = myRole === 'owner' || myRole === 'admin'

  const [members, setMembers] = useState([])
  const [loading, setLoading] = useState(true)
  const [addOpen, setAddOpen] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    if (!currentOrgId) return
    setLoading(true)
    try { setMembers(await listMembers(currentOrgId)) }
    catch { message.error('加载成员失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [currentOrgId])

  const onAdd = async () => {
    const values = await form.validateFields()
    try {
      await addMember(currentOrgId, values)
      message.success('已添加成员')
      setAddOpen(false); form.resetFields(); load()
    } catch (e) { message.error(e.response?.data?.detail || '添加失败') }
  }

  const onChangeRole = async (userId, role) => {
    try { await updateMemberRole(currentOrgId, userId, { role }); message.success('角色已更新'); load() }
    catch (e) { message.error(e.response?.data?.detail || '更新失败') }
  }

  const onChangeBudget = async (userId, budget_usd) => {
    try { await updateMemberRole(currentOrgId, userId, { budget_usd: budget_usd ?? 0 }); message.success('预算已更新'); load() }
    catch (e) { message.error(e.response?.data?.detail || '更新失败') }
  }

  const onRemove = async (userId) => {
    try { await removeMember(currentOrgId, userId); message.success('已移除'); load() }
    catch (e) { message.error(e.response?.data?.detail || '移除失败') }
  }

  const columns = [
    { title: '姓名', dataIndex: 'name' },
    { title: '邮箱', dataIndex: 'email' },
    {
      title: '角色', dataIndex: 'role',
      render: (role, r) => (
        myRole === 'owner' && r.user_id !== user?.id
          ? <Select size="small" value={role} style={{ width: 110 }} onChange={(v) => onChangeRole(r.user_id, v)}
              options={[{ value: 'member', label: 'member' }, { value: 'admin', label: 'admin' }, { value: 'owner', label: 'owner' }]} />
          : <Tag color={ROLE_COLOR[role]}>{role}</Tag>
      ),
    },
    {
      title: '成员预算 (USD)', dataIndex: 'budget_usd',
      render: (v, r) => myRole === 'owner'
        ? <InputNumber size="small" min={0} step={1} defaultValue={v} placeholder="不限" style={{ width: 110 }}
            onBlur={(e) => { const n = Number(e.target.value); if (n !== (v ?? 0)) onChangeBudget(r.user_id, n) }} />
        : (v != null ? `$${v}` : '不限'),
    },
    ...(canManage ? [{
      title: '操作',
      render: (_, r) => (
        r.user_id === user?.id ? <span style={{ color: '#aaa' }}>自己</span> :
        <Popconfirm title="移除该成员？" onConfirm={() => onRemove(r.user_id)}>
          <Button size="small" danger>移除</Button>
        </Popconfirm>
      ),
    }] : []),
  ]

  return (
    <div>
      {canManage && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
          <Button type="primary" icon={<UserAddOutlined />} onClick={() => setAddOpen(true)}>添加成员</Button>
        </div>
      )}
      <Table columns={columns} dataSource={members} rowKey="id" loading={loading} />

      <Modal title="添加成员" open={addOpen} onOk={onAdd} onCancel={() => setAddOpen(false)} okText="添加">
        <Form form={form} layout="vertical" initialValues={{ role: 'member' }}>
          <Form.Item name="email" label="用户邮箱（需已注册）" rules={[{ required: true, type: 'email' }]}>
            <Input placeholder="member@example.com" />
          </Form.Item>
          <Form.Item name="role" label="角色">
            <Select options={[
              { value: 'member', label: 'member（只读）' },
              { value: 'admin', label: 'admin（管理 Key/成员）' },
              ...(myRole === 'owner' ? [{ value: 'owner', label: 'owner（完全控制）' }] : []),
            ]} />
          </Form.Item>
          <Form.Item name="budget_usd" label="成员预算 USD（可选，留空=不限）">
            <InputNumber min={0.01} step={10} style={{ width: '100%' }} prefix="$" placeholder="该成员消费上限" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
