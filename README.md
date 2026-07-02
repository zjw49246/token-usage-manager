# Token Usage Manager（→ TokenRouter 改造中）

多供应商 LLM API 网关：通过生成的 API Key 授权其它应用调用模型，控制 Token 用量、调用次数、
USD 成本限额、可用模型、时间区间和 RPM 限速。模型路由由 **LiteLLM 内核 + 数据库模型目录**驱动
（openai / anthropic / google / deepseek / mistral / groq / xai / 火山 Ark），
每次调用按目录单价核算成本。内置 React 前端，可视化管理和查看用量。

> 正在按 `docs/TOKEN_ROUTER_TRANSFORM.md` 分期改造为 TokenRouter 式产品（当前已完成 P0/P1）。

## 架构

```
OpenAI SDK    ─┐
Anthropic SDK ─┼─→ TokenRouter (FastAPI) ──→ LiteLLM ──→ OpenAI / Anthropic / Gemini / DeepSeek / …
Gemini SDK    ─┘   │  三入口方言翻译（/v1/chat/completions · /v1/messages · /v1beta）
                   │  多租户鉴权（JWT + 组织 RBAC）+ API Key
                   │  配额检查（次数/Token/USD 成本/RPM）
                   │  模型目录（model_catalog：价格/上下文窗口）
                   │  用量与成本记录 (SQLite)
                   └─ React 前端 (前端 build 后由 FastAPI 托管)
```

**三种入口，一套 Key**：OpenAI、Anthropic(Claude)、Gemini 三家 SDK 都能把 base_url 指过来，
无需改代码即可路由到目录里的任意模型（见「接入指南」页）。

启动前需 seed 模型目录（否则 `/v1/models` 为空）：

```bash
cd backend && uv run python -m scripts.seed
```

各供应商凭证通过环境变量配置（`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` /
`DEEPSEEK_API_KEY` / …），只配了哪家就能用哪家的模型。

## 快速开始（Docker）

### 1. 配置环境变量

```bash
cd backend
cp .env.example .env
# 编辑 .env，填入真实的 GEMINI_API_KEY 和 ADMIN_TOKEN
```

### 2. 启动服务

```bash
docker compose up -d
```

服务访问：https://token.claude-code-manager.com（或本地 http://localhost:8001）

如需使用 Vertex AI 模式，取消 `docker-compose.yml` 中 credentials 挂载的注释。

### 3. 查看日志 / 停止

```bash
docker compose logs -f    # 查看日志
docker compose down        # 停止服务
```

数据库通过 Docker volume (`db-data`) 持久化，容器重建不会丢失数据。

## 本地开发（不用 Docker）

### 1. 后端

```bash
cd backend
cp .env.example .env
# 编辑 .env
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2. 构建前端（生产）

```bash
cd frontend
npm install
npm run build
# build 产物在 frontend/dist，FastAPI 启动时自动挂载
```

### 3. 开发模式（前后端分离）

```bash
# 终端1：后端
cd backend && uv run uvicorn app.main:app --reload

# 终端2：前端（带代理，自动转发 /admin /v1 到后端）
cd frontend && npm run dev
```

前端访问：http://localhost:5173（开发）或 http://localhost:8000（生产）

## 客户端接入

其它应用只需替换 `base_url` 和 `api_key`：

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url="http://your-server:8000/v1",
    api_key="tum_xxxxxxxx...",  # 从管理后台创建
)
response = await client.chat.completions.create(
    model="gemini-2.5-flash",
    messages=[{"role": "user", "content": "Hello"}],
)
```

## 配置说明（.env）

| 变量 | 说明 | 默认 |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API Key（上游真实凭证） | 必填 |
| `GEMINI_OPENAI_BASE_URL` | 上游 OpenAI 兼容接口地址 | Google 官方地址 |
| `ADMIN_TOKEN` | 管理后台鉴权 Token | `change-me`（必须修改） |
| `DATABASE_URL` | SQLite 数据库路径 | `sqlite+aiosqlite:///./data/token_manager.db` |
| `PORT` | 服务端口 | `8000` |

## API Key 权限控制

创建 Key 时可配置：
- **allowed_models**：允许使用的模型列表（留空=不限）
- **max_total_tokens**：Token 总上限
- **max_calls**：调用次数上限
- **max_rpm**：每分钟请求数限速
- **valid_from / valid_until**：生效时间区间

## 前端功能

- **Dashboard**：总览卡片、Token 趋势折线图、各 Key 占比饼图
- **API Keys**：列表、创建（含配置）、启停、删除
- **Key 详情**：配置编辑、用量进度、调用明细表格
- **接入指南**：多语言示例代码（Python / Node.js / cURL）、可用模型列表、注意事项
- **Settings**：Admin Token 配置、接入说明

## API 文档

启动后访问 https://token.claude-code-manager.com/api/docs（或本地 http://localhost:8001/api/docs）
