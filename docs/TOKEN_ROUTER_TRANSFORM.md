# Token Usage Manager → TokenRouter 改造方案

> 目标：把当前的「单租户 Gemini/DeepSeek 用量代理」改造成对齐 tokenrouter.com 的
> 「多供应商 · 多入口协议 · 按成本计费 · 多租户 SaaS」统一 AI 模型枢纽。
>
> 已确认的 4 个方向决定：
> 1. **路由内核**：内嵌 LiteLLM（拿 100+ 供应商 + 多方言适配 + 每模型价格表）
> 2. **入口协议**：一步到位，OpenAI + Claude + Gemini 三入口全上
> 3. **计费模型**：升级到按 USD 成本 / credit 核算（token 也保留）
> 4. **租户形态**：直接做多租户 SaaS（组织 / 团队 / RBAC / 独立计费）

---

## 1. 当前架构现状（改造起点）

| 层 | 现状 | 主要文件 |
|---|---|---|
| 入口 | 仅 OpenAI 格式：`GET /v1/models`、`POST /v1/chat/completions` | `routers/proxy.py` |
| 路由 | 硬编码 `if/else`：`_is_deepseek_model()` 前缀判断 → Gemini(OpenAI 兼容 / Vertex) 或 DeepSeek | `services/proxy.py` |
| 模型 | 两个写死的 Python list + `_MODEL_OWNER` dict，无价格 | `routers/proxy.py` |
| 鉴权 | 客户端 `tum_` API Key（SHA256）；管理端单一静态 `ADMIN_TOKEN` | `dependencies.py`, `services/auth.py` |
| 配额 | 每 Key：allowed_models / max_total_tokens / max_calls / max_rpm / 有效期；**已修并发原子预扣** | `services/quota.py` |
| 计量 | 只数 token + 调用次数 | `models.py`, `services/quota.py` |
| 存储 | SQLite + WAL，`Base.metadata.create_all()`，**无 Alembic 迁移** | `database.py` |
| 前端 | React18 + Vite6 + antd5 + zustand + recharts；4 页：总览 / API Keys / 接入指南 / 设置；管理端凭 localStorage 里的 admin token | `frontend/src/**` |
| 部署 | Docker + docker-compose，FastAPI 托管前端 build 产物 | `Dockerfile`, `docker-compose.yml` |

**核心瓶颈**：路由是硬编码而非数据驱动；只有单 admin 无真正账户体系；只认 OpenAI 一种格式；只数 token 不算钱。

---

## 2. 目标架构

```
                         ┌────────────────── 入口协议层（三方言）──────────────────┐
  OpenAI SDK  ──────────▶│  POST /v1/chat/completions        (OpenAI)              │
  Anthropic SDK ────────▶│  POST /v1/messages                (Claude Messages)     │
  Gemini SDK ───────────▶│  POST /v1beta/models/{m}:generateContent (Gemini 原生)  │
                         └───────────────────────┬────────────────────────────────┘
                                                 │  统一为内部规范请求(OpenAI messages)
                         ┌───────────────────────▼────────────────────────────────┐
   治理层（保留+扩展）───▶│ 鉴权(API Key/JWT) · 组织/RBAC · 配额+成本预检 · 用量记账 │
                         └───────────────────────┬────────────────────────────────┘
                                                 │  model_id → catalog → litellm_model + 凭证
                         ┌───────────────────────▼────────────────────────────────┐
   路由内核（新）────────▶│      LiteLLM (litellm.acompletion / adapters)           │
                         └───────────────────────┬────────────────────────────────┘
                                                 ▼
                          OpenAI · Anthropic · Google · DeepSeek · Mistral · Groq · …（100+）
```

分三大块：**入口协议层**（方言互转）→ **治理层**（你的现有资产 + 多租户/成本扩展）→ **LiteLLM 路由内核**（替换硬编码）。

---

## 3. 数据模型设计

### 3.1 平台级（全租户共享）

**`providers`** — 供应商注册表（替代硬编码分支）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| name | str | openai / anthropic / google / deepseek / mistral / groq … |
| litellm_prefix | str | LiteLLM 前缀，如 `openai`、`gemini`、`deepseek` |
| api_base | str? | 自定义 base（如 DeepSeek 火山、Vertex）；空=用 LiteLLM 默认 |
| credential_ref | str | 凭证来源：env 变量名或密钥表 id |
| enabled | bool | |

**`model_catalog`** — 模型目录 + 价格（对比页 & 成本核算的数据源）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | |
| model_id | str unique | 对外公开的模型名，如 `gpt-4o`、`claude-sonnet-4-6` |
| provider_id | FK | |
| litellm_model | str | 传给 LiteLLM 的全名，如 `openai/gpt-4o` |
| display_name | str | |
| input_price_per_1m / output_price_per_1m | float | 每百万 token 单价（USD），seed 自 LiteLLM `model_cost` |
| context_window / max_output_tokens | int | |
| capabilities | JSON | ["chat","vision","tools","embedding","image","video"] |
| verified | bool | 对齐 TokenRouter「Verified Models」 |
| enabled | bool | |

### 3.2 租户级（多租户 SaaS 核心）

**`organizations`**：id, name, slug, credit_balance_usd(默认0), created_at
**`users`**：id, email(unique), password_hash(bcrypt), name, is_superadmin, created_at
**`memberships`**：id, org_id FK, user_id FK, role(`owner`/`admin`/`member`), created_at — RBAC 落点
**`credit_transactions`**：id, org_id FK, amount_usd(+充值/−消费/±调整), type, ref(usage_record_id), balance_after, created_at — 计费流水台账

### 3.3 现有表的扩展

- **`api_keys`** +：`org_id`(FK, 先可空便于回填)、`created_by_user_id`、`max_cost_usd`(USD 限额)
- **`usage_records`** +：`org_id`(反范式，租户查询提速)、`provider`、`cost_usd`、`input_price_snapshot`/`output_price_snapshot`
- **`usage_summary`**：保留每 Key 汇总（配额用）；组织级余额走 `organizations.credit_balance_usd` + 台账

### 3.4 迁移策略（重要）

现在用 `create_all` 无迁移。新增表可自动建，但**给已有表加列必须迁移** → **引入 Alembic**。
回填脚本：建默认组织 → 把现有 API Key 挂到默认组织 → 历史 usage 补 `org_id`。

---

## 4. 路由内核：LiteLLM 集成

新增 `services/router.py`，彻底替换 `services/proxy.py` 的硬编码分支：

```python
# 伪代码
row = await get_catalog(model_id)                    # 公开名 → 目录行
creds = resolve_credentials(row.provider)            # 供应商凭证（env/DB）
resp = await litellm.acompletion(
    model=row.litellm_model,                         # e.g. "gemini/gemini-2.5-flash"
    messages=canonical_messages, stream=is_stream,
    api_key=creds.key, api_base=row.provider.api_base or None,
    **passthrough_params,
)
usage = resp.usage                                   # 统一 usage
cost  = compute_cost(row, usage)                      # 用目录价格算（可控，匹配计费）
```

要点：
- **凭证按调用注入**（不写全局 env），多供应商 key 并存。
- **成本自算**：用 `model_catalog` 单价而非只靠 `litellm.completion_cost`，保证与计费口径一致。
- **把 LiteLLM 藏在自己的接口后面**（`Router` 类），版本 pin 死，将来可替换。

---

## 5. 三入口协议层

每个入口做「请求方言→内部规范(OpenAI messages)」和「规范响应→方言响应」的双向翻译（含流式 SSE）。新增 `dialects/` 模块。

| 入口 | 端点 | 实现 | 难度 |
|---|---|---|---|
| OpenAI | `POST /v1/chat/completions`（已有） | 规范格式本身，直通 | ★ |
| Anthropic | `POST /v1/messages` | LiteLLM `AnthropicAdapter` 转译请求/响应，流式映射 message_start / content_block_delta / … | ★★ |
| Gemini | `POST /v1beta/models/{model}:generateContent` 及 `:streamGenerateContent` | 自写轻量适配（Gemini `contents`↔OpenAI messages），LiteLLM 主要覆盖上游侧 | ★★★ |

统一经过同一路由内核 → **任何模型都能用任一方言调用**（这就是「换模型不改代码」的卖点）。

---

## 6. 成本核算与计费

- **记账**（`record_usage`）：`cost_usd = in/1e6*in_price + out/1e6*out_price`，写入 `usage_records`；原子扣减 `organizations.credit_balance_usd` 并追加 `credit_transactions`（复用已修的原子预扣模式）。
- **预检**（`check_quota`）：请求前廉价闸门 = 组织余额 > 0 且 该 Key 未超 `max_cost_usd`；请求后按实际 usage 精确扣费（成本事前不可知，属行业标准做法）。
- **报表**：Dashboard 增加「按成本 / 按供应商 / 按模型」维度。

---

## 7. 多租户与鉴权

**两个鉴权平面：**
1. **控制台（人）**：邮箱+密码 → JWT（access/refresh）。端点：`/auth/register`、`/auth/login`、`/auth/refresh`、`/auth/me`。密码 bcrypt(passlib)，JWT 用 pyjwt。
2. **代理调用（机器）**：保留 `tum_` API Key（SHA256），但现在**归属某个组织**，用于计费与配额。
3. **超级管理员**：平台运营者（管供应商、模型目录）——`is_superadmin` 用户或保留 bootstrap `ADMIN_TOKEN`。

**RBAC 角色：** owner（含计费/删组织/管成员）> admin（管 Key/看用量/管成员）> member（看用量、可选建 Key）。所有租户资源查询强制按 `org_id` 隔离。

---

## 8. 前端改造

- **新增页**：登录/注册、组织切换器、成员管理（邀请/角色）、计费（余额/充值/流水）、**模型目录/价格对比页**（对齐 TokenRouter `/models`）。
- **改造页**：Dashboard（成本+供应商维度）、API Keys（按组织隔离、加 `max_cost_usd`、模型选择改为拉目录 API）、接入指南（展示三种入口 base_url + OpenAI/Anthropic/Gemini SDK 示例）、设置（真正登录替代静态 admin token）。
- 鉴权 store 从「localStorage 存 admin token」升级为 JWT 会话。

---

## 9. 依赖变更

- **后端新增**：`litellm`（内核）、`pyjwt`、`passlib[bcrypt]`、`alembic`、`email-validator`。
- **前端**：基本沿用 antd + recharts，无重依赖新增。
- **未来（规模化）**：多 worker 的 RPM 限速需共享存储（Redis）；SQLite → Postgres（SQLAlchemy + Alembic 已保证可移植）。

---

## 10. 分期实施路线（每期一个 PR，提交+推送，测试全绿）

| 期 | 内容 | 交付标准 |
|---|---|---|
| **P0 地基** | 加依赖 + Alembic；建平台/租户新表；给旧表加列（org_id 可空、cost_usd）；用 LiteLLM `model_cost` seed 目录；回填默认组织 | 现有 OpenAI 路径行为不变，测试全绿 |
| **P1 内核** | `services/router.py` 用 LiteLLM 替换硬编码路由；`record_usage` 加成本；`/v1/models` 改查目录带价格 | Mock 上游下 OpenAI chat/completions 无回归 |
| **P2 多租户** | users/JWT 登录、组织/成员/RBAC，Key+用量+计费按 org 隔离；超管管目录/供应商；前端登录+组织切换+成员页 | 端到端登录→建组织→建 Key→调用→隔离生效 |
| **P3 三入口** | `/v1/messages`(Anthropic) + `/v1beta`(Gemini) 含流式 | 三方言各自 SDK 冒烟通过 |
| **P4 计费+目录 UI** | 余额/充值/台账、成本 Dashboard、模型对比页 | 成本口径与台账对账一致 |
| **P5 收尾** | 品牌改 TokenRouter；README/TEST/CLAUDE.md 同步；Docker/env 更新 | 文档与代码一致 |

---

## 11. 风险与测试策略

- **LiteLLM 重且演进快** → pin 版本，藏在自有接口后。
- **Gemini 入口翻译最难** → 单独模块 + 充分单测（多模态、tool、流式边界）。
- **流式跨方言的 usage/成本提取** → 每方言独立解析器 + 回归测试。
- **SQLite 撑多租户 SaaS 有限** → 保留 Postgres 迁移路径。
- **多 worker RPM** → 现为进程内，规模化上 Redis。
- **测试基线**：改代码前后各跑一遍 `uv run pytest`；每期新增对应回归用例并更新 TEST.md（遵循项目 CLAUDE.md 规范）。

---

## 12. 待你确认后即从 P0 开始

P0 全是「加表/加列/加依赖」的低风险地基工作，不改变现有 OpenAI 调用行为。确认后我按 CLAUDE.md 流程建分支 `feat/token-router-p0` 开工。
```
