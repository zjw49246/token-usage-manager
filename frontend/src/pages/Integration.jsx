import { Card, Typography, Tabs, Tag, Divider, Alert } from 'antd'
import { CopyOutlined } from '@ant-design/icons'

const { Text, Paragraph, Title } = Typography

function CodeBlock({ code, language }) {
  const copy = () => {
    navigator.clipboard.writeText(code)
    window.antd_message?.success?.('已复制') // fallback below
  }
  return (
    <div style={{ position: 'relative', background: '#1e1e1e', borderRadius: 8, padding: '16px 20px', marginBottom: 16, overflow: 'auto' }}>
      <button
        onClick={copy}
        style={{
          position: 'absolute', top: 8, right: 8, background: 'rgba(255,255,255,0.1)',
          border: 'none', borderRadius: 4, padding: '4px 8px', cursor: 'pointer', color: '#aaa', fontSize: 12,
          display: 'flex', alignItems: 'center', gap: 4,
        }}
        onMouseEnter={e => e.target.style.background = 'rgba(255,255,255,0.2)'}
        onMouseLeave={e => e.target.style.background = 'rgba(255,255,255,0.1)'}
      >
        <CopyOutlined /> 复制
      </button>
      {language && <Tag color="blue" style={{ position: 'absolute', top: 8, left: 12, fontSize: 11 }}>{language}</Tag>}
      <pre style={{ margin: 0, color: '#d4d4d4', fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre', overflowX: 'auto', paddingTop: language ? 20 : 0 }}>
        {code}
      </pre>
    </div>
  )
}

const BASE_URL = window.location.origin + '/v1'

const pythonAsync = `from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url="${BASE_URL}",
    api_key="tum_你的API Key",
)

response = await client.chat.completions.create(
    model="gemini-2.5-flash",
    messages=[
        {"role": "system", "content": "你是一个有帮助的助手。"},
        {"role": "user", "content": "你好，请介绍一下自己"},
    ],
)
print(response.choices[0].message.content)`

const pythonSync = `from openai import OpenAI

client = OpenAI(
    base_url="${BASE_URL}",
    api_key="tum_你的API Key",
)

response = client.chat.completions.create(
    model="gemini-2.5-flash",
    messages=[
        {"role": "user", "content": "Hello!"},
    ],
)
print(response.choices[0].message.content)`

const pythonStream = `from openai import OpenAI

client = OpenAI(
    base_url="${BASE_URL}",
    api_key="tum_你的API Key",
)

stream = client.chat.completions.create(
    model="gemini-2.5-flash",
    messages=[{"role": "user", "content": "写一首关于春天的诗"}],
    stream=True,
)

for chunk in stream:
    content = chunk.choices[0].delta.content
    if content:
        print(content, end="", flush=True)`

const nodeJs = `import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: '${BASE_URL}',
  apiKey: 'tum_你的API Key',
});

const response = await client.chat.completions.create({
  model: 'gemini-2.5-flash',
  messages: [
    { role: 'user', content: 'Hello!' },
  ],
});

console.log(response.choices[0].message.content);`

const nodeStream = `import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: '${BASE_URL}',
  apiKey: 'tum_你的API Key',
});

const stream = await client.chat.completions.create({
  model: 'gemini-2.5-flash',
  messages: [{ role: 'user', content: '讲一个笑话' }],
  stream: true,
});

for await (const chunk of stream) {
  const content = chunk.choices?.[0]?.delta?.content;
  if (content) process.stdout.write(content);
}`

const curlExample = `curl ${BASE_URL}/chat/completions \\
  -H "Authorization: Bearer tum_你的API Key" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gemini-2.5-flash",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'`

const curlStream = `curl ${BASE_URL}/chat/completions \\
  -H "Authorization: Bearer tum_你的API Key" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gemini-2.5-flash",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "stream": true
  }'`

const curlModels = `curl ${BASE_URL}/models \\
  -H "Authorization: Bearer tum_你的API Key"`

const pythonInstall = `pip install openai`
const nodeInstall = `npm install openai`

export default function Integration() {
  return (
    <div style={{ maxWidth: 860 }}>
      <Alert
        type="info"
        message="本服务兼容 OpenAI API 格式，只需替换 base_url 和 api_key 即可接入，无需修改现有代码逻辑。"
        style={{ marginBottom: 20 }}
      />

      <Card title="接入信息" style={{ marginBottom: 20 }}>
        <Paragraph>
          <Text strong>代理地址：</Text>
          <Text code copyable>{BASE_URL}</Text>
        </Paragraph>
        <Paragraph>
          <Text strong>API Key：</Text>
          <Text type="secondary">在 <a href="/keys">API Keys</a> 页面创建，格式为 </Text>
          <Text code>tum_xxxxxxxx...</Text>
        </Paragraph>
        <Paragraph>
          <Text strong>默认模型：</Text>
          <Text code>gemini-2.5-flash</Text>
          <Text type="secondary">（不指定 model 时使用）</Text>
        </Paragraph>
        <Paragraph style={{ marginBottom: 0 }}>
          <Text strong>可用模型：</Text>
          <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <Tag color="purple">gemini-3.1-pro-preview</Tag>
            <Tag color="purple">gemini-3-flash-preview</Tag>
            <Tag color="purple">gemini-3.1-flash-lite-preview</Tag>
            <Tag color="blue">gemini-2.5-pro</Tag>
            <Tag color="blue">gemini-2.5-flash</Tag>
            <Tag color="blue">gemini-2.5-flash-lite</Tag>
            <Tag color="default">gemini-2.0-flash</Tag>
          </div>
        </Paragraph>
      </Card>

      <Card title="示例代码">
        <Tabs items={[
          {
            key: 'python',
            label: 'Python',
            children: (
              <div>
                <Title level={5}>安装依赖</Title>
                <CodeBlock code={pythonInstall} language="bash" />

                <Title level={5}>异步调用</Title>
                <CodeBlock code={pythonAsync} language="python" />

                <Title level={5}>同步调用</Title>
                <CodeBlock code={pythonSync} language="python" />

                <Title level={5}>流式输出</Title>
                <CodeBlock code={pythonStream} language="python" />
              </div>
            ),
          },
          {
            key: 'node',
            label: 'Node.js',
            children: (
              <div>
                <Title level={5}>安装依赖</Title>
                <CodeBlock code={nodeInstall} language="bash" />

                <Title level={5}>基本调用</Title>
                <CodeBlock code={nodeJs} language="javascript" />

                <Title level={5}>流式输出</Title>
                <CodeBlock code={nodeStream} language="javascript" />
              </div>
            ),
          },
          {
            key: 'curl',
            label: 'cURL',
            children: (
              <div>
                <Title level={5}>基本请求</Title>
                <CodeBlock code={curlExample} language="bash" />

                <Title level={5}>流式请求</Title>
                <CodeBlock code={curlStream} language="bash" />

                <Title level={5}>查询可用模型</Title>
                <CodeBlock code={curlModels} language="bash" />
              </div>
            ),
          },
        ]} />
      </Card>

      <Card title="注意事项" style={{ marginTop: 20 }}>
        <ul style={{ paddingLeft: 20, margin: 0, lineHeight: 2.2 }}>
          <li>API Key 创建后仅显示一次完整密钥，请妥善保管</li>
          <li>每个 Key 可独立配置模型白名单、Token 上限、调用次数上限、RPM 限速和生效时间</li>
          <li>超出配额后请求将返回 <Text code>429</Text> 错误</li>
          <li>Key 被停用后请求将返回 <Text code>403</Text> 错误</li>
          <li>流式和非流式请求均会自动统计 Token 用量</li>
          <li>所有请求参数与 <a href="https://platform.openai.com/docs/api-reference/chat" target="_blank" rel="noopener noreferrer">OpenAI Chat Completions API</a> 完全一致</li>
        </ul>
      </Card>
    </div>
  )
}
