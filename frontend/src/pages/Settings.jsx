import { Card, Descriptions, Typography, Tag, Alert } from 'antd'
import { useAuthStore } from '../stores/authStore.js'

const ROLE_COLOR = { owner: 'gold', admin: 'blue', member: 'default' }

export default function Settings() {
  const { user, currentOrg } = useAuthStore()
  const org = currentOrg()

  return (
    <div style={{ maxWidth: 680 }}>
      <Card title="账户信息">
        <Descriptions column={1} size="small">
          <Descriptions.Item label="姓名">{user?.name}</Descriptions.Item>
          <Descriptions.Item label="邮箱">{user?.email}</Descriptions.Item>
          <Descriptions.Item label="平台超管">{user?.is_superadmin ? '是' : '否'}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="当前组织" style={{ marginTop: 16 }}>
        <Descriptions column={1} size="small">
          <Descriptions.Item label="组织名称">{org?.name}</Descriptions.Item>
          <Descriptions.Item label="标识">{org?.slug}</Descriptions.Item>
          <Descriptions.Item label="我的角色"><Tag color={ROLE_COLOR[org?.role]}>{org?.role}</Tag></Descriptions.Item>
          <Descriptions.Item label="额度余额">${(org?.credit_balance_usd ?? 0).toFixed(2)}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="服务信息" style={{ marginTop: 16 }}>
        <Alert type="info" showIcon style={{ marginBottom: 16 }}
          message="鉴权已升级为账户登录（JWT），不再需要手动填写 Admin Token。" />
        <Typography.Paragraph>
          <strong>代理接口地址：</strong><Typography.Text code>{window.location.origin}/v1</Typography.Text>
        </Typography.Paragraph>
        <Typography.Paragraph>
          <strong>使用方式：</strong>把客户端 SDK 的 <Typography.Text code>base_url</Typography.Text> 指向上方地址，
          <Typography.Text code>api_key</Typography.Text> 填入「API Keys」页创建的 Key，即可调用目录中的任意模型。
        </Typography.Paragraph>
        <Typography.Paragraph>
          <strong>API 文档：</strong><a href="/api/docs" target="_blank" rel="noreferrer">/api/docs</a>
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
