# TokenRouter

统一的多供应商 AI 模型网关：把 OpenAI / Anthropic / Google / DeepSeek / Mistral / Groq / xAI 等
700+ 模型聚合成一套接口，**同时兼容 OpenAI、Anthropic(Claude)、Gemini 三种 API 格式**——
任意一家 SDK 把 `base_url` 指过来即可，无需改代码即可切换模型。内置多租户管理后台：
组织/成员 RBAC、每 Key 配额、按 USD 成本的预付费计费、模型价格对比。

## 架构

```
OpenAI SDK    ─┐
Anthropic SDK ─┼─→ TokenRouter (FastAPI) ──→ LiteLLM ──→ OpenAI / Anthropic / Gemini / DeepSeek / …
Gemini SDK    ─┘   │  三入口方言翻译（/v1/chat/completions · /v1/messages · /v1beta）
                   │  多租户鉴权（JWT + 组织 RBAC）+ 代理 API Key
                   │  配额（次数/Token/USD 成本/RPM）+ 预付费额度闸门
                   │  模型目录（价格/上下文窗口）+ 用量与成本记录 (SQLite)
                   └─ React 前端 (build 后由 FastAPI 托管)
```

- **后端**：FastAPI + SQLAlchemy 2.0 async + SQLite(WAL)，`uv` 管理依赖，LiteLLM 路由内核
- **前端**：React 18 + Vite + Ant Design 5
- **迁移**：Alembic（`backend/alembic/`）；模型目录首次启动自动 seed（幂等）

## 快速开始（Docker）

```bash
cd backend
cp .env.example .env
# 编辑 .env：填入至少一家供应商的 API Key + ADMIN_TOKEN + JWT_SECRET
cd .. && docker compose up -d
```

访问 http://localhost:8001 —— 打开即是 TokenRouter 登录页，注册账号（自动赠送启动额度）即可用。
模型目录在首次启动时自动灌入（含各家价格），无需手动 seed。

```bash
docker compose logs -f   # 日志
docker compose down       # 停止（数据在 db-data volume 中持久化）
```

## 本地开发

```bash
# 后端
cd backend
cp .env.example .env    # 编辑 .env
uv sync
uv run uvicorn app.main:app --reload      # 首次启动自动 seed 模型目录

# 前端（另一个终端）
cd frontend
npm install
npm run dev             # 开发模式 http://localhost:5173（自动代理 API 到后端）
# 或 npm run build 生成 dist，由后端在 http://localhost:8000 托管
```

数据库 schema 演进用 Alembic（已有部署先 `alembic stamp 001` 再 `alembic upgrade head`）。

## 客户端接入（三种入口，一套 Key）

在后台创建 API Key（`tum_...`），三家 SDK 任选其一：

```python
# OpenAI 格式
from openai import OpenAI
client = OpenAI(base_url="http://your-server:8001/v1", api_key="tum_...")
client.chat.completions.create(model="gpt-4o", messages=[{"role":"user","content":"Hi"}])

# Anthropic(Claude) 格式 —— POST /v1/messages
from anthropic import Anthropic
client = Anthropic(base_url="http://your-server:8001", api_key="tum_...")
client.messages.create(model="claude-sonnet-4-6", max_tokens=1024,
                       messages=[{"role":"user","content":"Hi"}])

# Gemini 格式 —— /v1beta/models/{model}:generateContent
from google import genai
client = genai.Client(api_key="tum_...", http_options={"base_url":"http://your-server:8001"})
client.models.generate_content(model="gemini-2.5-flash", contents="Hi")
```

`model` 填模型目录里的任意名字即可（在「模型目录」页查看全部 700+ 模型与价格）。

## 配置说明（.env）

| 变量 | 说明 | 默认 |
|---|---|---|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` / `MISTRAL_API_KEY` / `GROQ_API_KEY` / `XAI_API_KEY` | 各供应商上游凭证（配了哪家用哪家） | 全部可选 |
| `ADMIN_TOKEN` | 平台超管 Token（供应商/目录等平台级运维） | `change-me`（必须改） |
| `JWT_SECRET` | 用户登录 JWT 密钥（`openssl rand -hex 32`） | 必须改 |
| `WELCOME_CREDIT_USD` | 新组织赠送启动额度（USD） | `5.0` |
| `ENFORCE_CREDIT_BALANCE` | 余额 ≤ 0 时是否拦截调用（402） | `true` |
| `DATABASE_URL` | SQLite 数据库路径 | `sqlite+aiosqlite:///./data/token_manager.db` |
| `PORT` | 服务端口 | `8000` |

## 权限与计费

- **组织 RBAC**：owner（含计费/删组织）> admin（管 Key/成员）> member（只读）
- **每 Key 配额**：allowed_models / max_total_tokens / max_calls / max_rpm / **max_cost_usd** / 有效期
- **预付费额度**：组织有 USD 余额，每次调用按模型单价扣减并记台账；余额 ≤ 0 拒绝（可关）

## 前端功能

- **总览**：成本/Token/调用卡片、趋势折线图、各 Key 占比饼图（按当前组织）
- **API Keys**：列表/创建/启停/删除，含成本上限与目录模型选择
- **模型目录**：700+ 模型对比（供应商/输入输出价/上下文窗口/能力/verified，可搜索排序）
- **额度计费**：余额、充值（owner）、额度流水台账
- **成员**：邀请/移除成员、改角色（RBAC）
- **接入指南**：OpenAI / Anthropic / Gemini 三种 SDK 示例
- **组织切换器 + 登录注册**：多租户账户体系

## 命令行工具（CLI）

```bash
cd backend
export TR_BASE_URL=http://localhost:8001   # 或线上地址
uv run python -m app.cli login -e you@example.com
uv run python -m app.cli models --mode chat        # 列模型
uv run python -m app.cli keys create --name app --max-cost 10
uv run python -m app.cli usage                       # 用量总览
uv run python -m app.cli balance                     # 余额
uv run python -m app.cli topup 50                    # 充值
```

配置存 `~/.tokenrouter/config.json`。`pip install .` 后可直接用 `tr <命令>`。

## API 文档

启动后访问 `/api/docs`（本地 http://localhost:8001/api/docs）。
