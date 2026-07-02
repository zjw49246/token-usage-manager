import { useEffect, useState } from 'react'
import { Row, Col, Card, Segmented, Spin, Typography, Empty } from 'antd'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell, Tooltip as PieTooltip
} from 'recharts'
import { getOverview, getTrend, getKeyShares } from '../api/index.js'
import { useAuthStore } from '../stores/authStore.js'
import StatCard from '../components/StatCard.jsx'

const COLORS = ['#1677ff', '#52c41a', '#fa8c16', '#f5222d', '#722ed1', '#13c2c2']

function fmt(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n
}

export default function Dashboard() {
  const orgId = useAuthStore((s) => s.currentOrgId)
  const [overview, setOverview] = useState(null)
  const [trend, setTrend] = useState([])
  const [shares, setShares] = useState([])
  const [granularity, setGranularity] = useState('day')
  const [loading, setLoading] = useState(true)

  const loadData = async () => {
    if (!orgId) return
    setLoading(true)
    try {
      const [ov, tr, sh] = await Promise.all([
        getOverview(orgId),
        getTrend(orgId, { granularity, days: granularity === 'hour' ? 1 : 7 }),
        getKeyShares(orgId),
      ])
      setOverview(ov)
      setTrend(tr.points)
      setShares(sh)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadData() }, [granularity, orgId])

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={5}>
          <StatCard title="累计成本 (USD)" value={`$${(overview?.total_cost_usd ?? 0).toFixed(4)}`} loading={loading} valueStyle={{ color: '#722ed1' }} />
        </Col>
        <Col xs={24} sm={12} lg={5}>
          <StatCard title="今日成本 (USD)" value={`$${(overview?.today_cost_usd ?? 0).toFixed(4)}`} loading={loading} valueStyle={{ color: '#eb2f96' }} />
        </Col>
        <Col xs={24} sm={12} lg={5}>
          <StatCard title="累计 Token 用量" value={fmt(overview?.total_tokens ?? 0)} loading={loading} valueStyle={{ color: '#1677ff' }} />
        </Col>
        <Col xs={24} sm={12} lg={5}>
          <StatCard title="今日调用次数" value={overview?.today_calls ?? 0} loading={loading} valueStyle={{ color: '#fa8c16' }} />
        </Col>
        <Col xs={24} sm={12} lg={4}>
          <StatCard title="活跃 Key" value={overview?.active_keys ?? 0} suffix={`/ ${overview?.total_keys ?? 0}`} loading={loading} />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={16}>
          <Card
            title="Token 用量趋势"
            extra={
              <Segmented
                size="small"
                options={[{ label: '按天（7天）', value: 'day' }, { label: '按小时（24h）', value: 'hour' }]}
                value={granularity}
                onChange={setGranularity}
              />
            }
          >
            {loading ? <Spin style={{ display: 'block', margin: '60px auto' }} /> : (
              trend.length === 0 ? <Empty description="暂无数据" style={{ margin: '40px 0' }} /> : (
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={trend}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="time" tick={{ fontSize: 12 }} />
                    <YAxis tickFormatter={fmt} tick={{ fontSize: 12 }} />
                    <Tooltip formatter={(v) => fmt(v)} />
                    <Legend />
                    <Line type="monotone" dataKey="tokens" name="Tokens" stroke="#1677ff" dot={false} strokeWidth={2} />
                    <Line type="monotone" dataKey="calls" name="调用次数" stroke="#52c41a" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              )
            )}
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="各 Key Token 占比" style={{ height: '100%' }}>
            {loading ? <Spin style={{ display: 'block', margin: '60px auto' }} /> : (
              shares.length === 0 ? <Empty description="暂无数据" style={{ margin: '40px 0' }} /> : (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={shares}
                      dataKey="tokens"
                      nameKey="name"
                      cx="50%" cy="50%"
                      outerRadius={90}
                      label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    >
                      {shares.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                    </Pie>
                    <PieTooltip formatter={(v) => fmt(v)} />
                  </PieChart>
                </ResponsiveContainer>
              )
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
