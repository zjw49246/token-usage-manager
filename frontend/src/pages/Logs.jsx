import { useEffect, useState } from 'react'
import { Card, Table, Tag, Space, Input, Select, DatePicker, Button, message } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getOrgUsage, exportOrgUsageUrl } from '../api/index.js'
import api from '../api/index.js'
import { useAuthStore } from '../stores/authStore.js'

function fmt(n) { return (n ?? n === 0) ? n : '—' }

export default function Logs() {
  const orgId = useAuthStore((s) => s.currentOrgId)
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState({ model: '', status: undefined, start_time: undefined, end_time: undefined })

  const load = async () => {
    if (!orgId) return
    setLoading(true)
    try { setData(await getOrgUsage(orgId, { page, page_size: 20, ...filters })) }
    catch { message.error('加载失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [orgId, page, filters])

  const doExport = async () => {
    try {
      const resp = await api.get(exportOrgUsageUrl(orgId, filters), { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([resp.data]))
      const a = document.createElement('a')
      a.href = url; a.download = `usage-org${orgId}.csv`; a.click()
      URL.revokeObjectURL(url)
    } catch { message.error('导出失败') }
  }

  const columns = [
    { title: '时间', dataIndex: 'created_at', render: (v) => dayjs(v).format('MM-DD HH:mm:ss') },
    { title: '模型', dataIndex: 'model' },
    { title: '供应商', dataIndex: 'provider', render: (v) => v || '—' },
    { title: '输入', dataIndex: 'input_tokens', render: fmt },
    { title: '输出', dataIndex: 'output_tokens', render: fmt },
    { title: '合计', dataIndex: 'total_tokens', render: fmt },
    { title: '成本', dataIndex: 'cost_usd', render: (v) => v != null ? `$${v.toFixed(6)}` : '—' },
    { title: '耗时', dataIndex: 'duration_ms', render: (v) => v ? `${v}ms` : '—' },
    {
      title: '状态', key: 'status',
      render: (_, r) => r.cached ? <Tag color="cyan">缓存</Tag> : <Tag color={r.status === 'success' ? 'green' : 'red'}>{r.status}</Tag>,
    },
  ]

  return (
    <Card
      title="请求日志"
      extra={
        <Space>
          <Input placeholder="模型" allowClear style={{ width: 150 }} onChange={(e) => { setPage(1); setFilters((f) => ({ ...f, model: e.target.value })) }} />
          <Select placeholder="状态" allowClear style={{ width: 110 }} onChange={(v) => { setPage(1); setFilters((f) => ({ ...f, status: v })) }}
            options={[{ value: 'success', label: 'success' }, { value: 'error', label: 'error' }]} />
          <DatePicker.RangePicker showTime onChange={(v) => { setPage(1); setFilters((f) => ({ ...f, start_time: v?.[0]?.toISOString(), end_time: v?.[1]?.toISOString() })) }} />
          <Button icon={<ReloadOutlined />} onClick={load} />
          <Button icon={<DownloadOutlined />} onClick={doExport}>导出 CSV</Button>
        </Space>
      }
    >
      <Table columns={columns} dataSource={data.items} rowKey="id" loading={loading} size="small"
        pagination={{ current: page, pageSize: 20, total: data.total, onChange: setPage, showTotal: (t) => `共 ${t} 条` }} />
    </Card>
  )
}
