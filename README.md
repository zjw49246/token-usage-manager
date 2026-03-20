# Token Usage Manager

一个 Gemini API 使用权限管理代理，支持通过生成的 API Key 授权其它应用调用模型，并控制 Token 用量、调用次数、可用模型、时间区间和 RPM 限速。内置 React 前端，可视化管理和查看用量。

## 架构

```
客户端 App ──→ Token Usage Manager (FastAPI) ──→ Gemini API
               │  API Key 校验
               │  配额检查
               │  用量记录 (SQLite)
               └─ React 前端 (前端 build 后由 FastAPI 托管)
```

## 快速开始

### 1. 后端配置

```bash
cd backend
cp .env.example .env
# 编辑 .env，填入真实的 GEMINI_API_KEY 和 ADMIN_TOKEN
```

### 2. 安装依赖并启动后端

```bash
cd backend
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3. 构建前端（生产）

```bash
cd frontend
npm install
npm run build
# build 产物在 frontend/dist，FastAPI 启动时自动挂载
```

### 4. 开发模式（前后端分离）

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

启动后访问 http://localhost:8000/api/docs
