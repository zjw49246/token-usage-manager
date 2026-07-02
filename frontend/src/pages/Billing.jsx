import { useEffect, useState } from 'react'
import { Card, Statistic, Button, Table, Tag, Modal, Form, InputNumber, Input, message, Row, Col } from 'antd'
import { DollarOutlined, PlusOutlined, CreditCardOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getCredits, topupCredits, createCheckout } from '../api/index.js'
import { useAuthStore } from '../stores/authStore.js'

const TYPE_META = {
  grant: { color: 'green', label: '赠送' },
  topup: { color: 'blue', label: '充值' },
  usage: { color: 'volcano', label: '消费' },
  adjustment: { color: 'gold', label: '调整' },
}

export default function Billing() {
  const { currentOrgId, currentOrg } = useAuthStore()
  const isOwner = currentOrg()?.role === 'owner'
  const [data, setData] = useState({ balance_usd: 0, transactions: [] })
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    if (!currentOrgId) return
    setLoading(true)
    try { setData(await getCredits(currentOrgId)) }
    catch { message.error('加载额度失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [currentOrgId])

  const onTopup = async () => {
    const values = await form.validateFields()
    try {
      await topupCredits(currentOrgId, values)
      message.success('充值成功')
      setOpen(false); form.resetFields(); load()
    } catch (e) { message.error(e.response?.data?.detail || '充值失败') }
  }

  const onStripe = async () => {
    const values = await form.validateFields()
    try {
      const { checkout_url } = await createCheckout(currentOrgId, {
        amount_usd: values.amount_usd,
        success_url: window.location.href,
        cancel_url: window.location.href,
      })
      window.location.href = checkout_url  // 跳转到 Stripe 支付页
    } catch (e) {
      message.error(e.response?.data?.detail || 'Stripe 未配置，请用手动充值')
    }
  }

  const columns = [
    { title: '时间', dataIndex: 'created_at', render: v => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
    { title: '类型', dataIndex: 'type', render: t => <Tag color={TYPE_META[t]?.color}>{TYPE_META[t]?.label || t}</Tag> },
    { title: '金额', dataIndex: 'amount_usd', render: v => <span style={{ color: v >= 0 ? '#52c41a' : '#f5222d' }}>{v >= 0 ? '+' : ''}${v.toFixed(6)}</span> },
    { title: '余额', dataIndex: 'balance_after', render: v => `$${v.toFixed(6)}` },
    { title: '备注', dataIndex: 'ref', render: v => v || '—' },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Statistic title="当前额度余额" value={data.balance_usd} precision={4} prefix={<DollarOutlined />}
              valueStyle={{ color: data.balance_usd > 0 ? '#3f8600' : '#cf1322' }} />
            {isOwner && (
              <Button type="primary" icon={<PlusOutlined />} style={{ marginTop: 16 }} onClick={() => setOpen(true)}>
                充值
              </Button>
            )}
          </Card>
        </Col>
      </Row>

      <Card title="额度流水">
        <Table columns={columns} dataSource={data.transactions} rowKey="id" loading={loading} size="small"
          pagination={{ pageSize: 20 }} />
      </Card>

      <Modal
        title="充值额度" open={open} onCancel={() => setOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setOpen(false)}>取消</Button>,
          <Button key="stripe" icon={<CreditCardOutlined />} onClick={onStripe}>Stripe 在线支付</Button>,
          <Button key="manual" type="primary" onClick={onTopup}>手动入账</Button>,
        ]}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="amount_usd" label="金额 (USD)" rules={[{ required: true }]}>
            <InputNumber min={0.01} step={10} style={{ width: '100%' }} prefix="$" placeholder="如：50" />
          </Form.Item>
          <Form.Item name="note" label="备注（手动入账用，可选）">
            <Input placeholder="如：季度预算" maxLength={100} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
