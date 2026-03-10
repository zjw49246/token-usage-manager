import { Card, Statistic } from 'antd'

export default function StatCard({ title, value, suffix, prefix, valueStyle, loading }) {
  return (
    <Card style={{ height: '100%' }}>
      <Statistic
        title={title}
        value={value}
        suffix={suffix}
        prefix={prefix}
        valueStyle={valueStyle}
        loading={loading}
      />
    </Card>
  )
}
