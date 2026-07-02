# 测试指南

## 后端单元测试

```bash
cd backend
uv run pytest tests/ -v
```

当前测试覆盖：

| 测试文件 | 用例 | 说明 |
|---|---|---|
| `test_auth.py` | Key 生成格式校验 | 前缀、哈希长度、确定性 |
| `test_auth.py` | Key 创建 + 验证 | 端到端创建并用于 /v1/models |
| `test_auth.py` | 无效 Key 拒绝 | 返回 401 |
| `test_quota.py` | 模型白名单 | 只返回允许的模型 |
| `test_quota.py` | 时间区间限制 | 过期 Key 返回 403 |
| `test_quota.py` | Admin CRUD | 创建/列表/更新/删除/404 |
| `test_quota.py` | 统计接口 | /admin/stats/overview 返回正确字段 |
| `test_quota.py` | 并发不绕过调用配额 | max_calls=3 并发 20 次，恰好放行 3 次，其余 429 |
| `test_quota.py` | 并发记账不崩 | 首次并发记账无 UNIQUE 冲突，token 累加无丢失 |
| `test_p0_schema.py` | 新表 CRUD 冒烟 | 多租户/供应商/目录/台账新表可写可查 |
| `test_p0_schema.py` | seed 幂等 | 两次 seed 结果一致；litellm 灌入 >100 模型；遗留模型名仍在目录 |
| `test_p0_schema.py` | 默认组织回填 | 已有 API Key 在 seed 后回填到默认组织 |
| `test_router.py` | /v1/models 带价格 | 目录驱动，返回单价/上下文窗口/能力扩展字段 |
| `test_router.py` | 未知模型 404 | OpenAI 风格 model_not_found |
| `test_router.py` | 非流式成本记账 | mock litellm，按目录单价核算 cost_usd 并原子累加 |
| `test_router.py` | USD 成本限额 | 累计成本超 max_cost_usd 后 429 |
| `test_router.py` | 流式 SSE + usage | OpenAI SSE 回吐（含 [DONE]），尾部 chunk 提取 usage 记账 |
| `test_router.py` | 上游错误映射 | litellm 异常按 status_code 透传，记 error 明细 |
| `test_multitenant.py` | 注册/登录/me/个人组织 | 注册即建个人组织(owner)，JWT 全流程 |
| `test_multitenant.py` | 重复邮箱/错误登录 | 409 / 401 |
| `test_multitenant.py` | 无效 token 拒绝 | 401 |
| `test_multitenant.py` | refresh 流程 | refresh 换新 token；access token 不能当 refresh |
| `test_multitenant.py` | org Key 隔离 | 非成员 403；跨组织看不到/删不了别人的 Key |
| `test_multitenant.py` | RBAC member 建 Key | member 可查看不可建（需 admin+） |
| `test_multitenant.py` | RBAC admin 授权 | admin 不能授予 owner 角色 |
| `test_multitenant.py` | 最后一个 owner 保护 | 不能降级/移除最后一个 owner |
| `test_multitenant.py` | org 统计隔离 | overview 只统计本组织，含成本字段 |
| `test_ingress_dialects.py` | Anthropic 非流式 | /v1/messages 返回 Anthropic 形状，system→OpenAI messages，成本记账 |
| `test_ingress_dialects.py` | Anthropic 流式 | message_start/content_block_delta/message_stop 事件，文本拼接正确 |
| `test_ingress_dialects.py` | Gemini 非流式 | generateContent 返回 candidates/usageMetadata，config 翻译 |
| `test_ingress_dialects.py` | Gemini 流式 | streamGenerateContent SSE，尾块带 usageMetadata |
| `test_ingress_dialects.py` | 入口未知模型 404 | 三入口共用目录解析 |
| `test_ingress_dialects.py` | 入口缺 Key 401 | x-api-key/x-goog-api-key/?key/Bearer 都没有时拒绝 |
| `test_billing.py` | 启动额度赠送 | 注册即赠送 welcome_credit_usd，有 grant 台账 |
| `test_billing.py` | 充值权限 | owner 充值成功并记 topup；member 充值 403 |
| `test_billing.py` | 欠额闸门 | 余额<=0 时调用返回 402 |
| `test_billing.py` | 消费扣减台账 | 调用后余额按成本减少，生成 usage 台账 |
| `test_failover.py` | 故障转移 | 通道A失败自动转通道B成功 |
| `test_failover.py` | 全部失败 | 所有通道失败返回上游状态码 |
| `test_failover.py` | 重试上限 | max_retries 限制最多尝试通道数 |
| `test_failover.py` | 无通道兼容 | 未配通道时回退单路由仍成功 |
| `test_failover.py` | 通道管理权限 | 普通用户 403；超管可 CRUD，凭证不回显明文 |
| `test_cache.py` | 相同请求命中缓存 | 第二次相同请求不打上游 |
| `test_cache.py` | 不同请求未命中 | 内容不同各打一次上游 |
| `test_cache.py` | 命中折算计费 | 命中记 cached=True，成本按 multiplier（0=免费），provider=cache，tokens 仍记 |
| `test_cache.py` | 流式不缓存 | 流式请求两次都打上游 |
| `test_cache.py` | 关闭缓存 | cache_enabled=false 时每次都打上游 |
| `test_endpoints.py` | embeddings 端点 | /v1/embeddings 回显公开名，按 token 计价记账 |
| `test_endpoints.py` | image 按张计价 | /v1/images/generations 按 n×image_price 计费 |
| `test_endpoints.py` | 目录暴露 mode | catalog 返回 mode/image_price（chat/embedding/image）|
| `test_endpoints.py` | 端点未知模型 404 | embeddings 未知模型 404 |
| `test_stripe.py` | 未配置拦截 | 未配 Stripe 时 checkout 返回 400 |
| `test_stripe.py` | checkout 返回 URL | owner 发起返回支付跳转 URL |
| `test_stripe.py` | webhook 幂等入账 | 同一支付 ref 只入账一次，余额+50 |
| `test_stripe.py` | webhook 忽略非充值 | 非充值完成事件不入账 |
| `test_member_budget.py` | 成员预算回显+强制 | 设成员预算并回显；累计消费超预算返回 429 |
| `test_member_budget.py` | 无预算不限 | 未设预算的成员可无限调用 |
| `test_sso.py` | providers 反映配置 | 未配空；配了 github 返回 [github] |
| `test_sso.py` | 授权 URL | 返回带 client_id/redirect_uri/state 的 authorize_url |
| `test_sso.py` | 未配置拦截 | 未配 provider 的 /url 返回 400 |
| `test_sso.py` | exchange 首次建号 | code 换 JWT，首登自动建用户+个人组织 |
| `test_sso.py` | exchange 已有邮箱登录 | 邮箱已存在则登录同账号不重复建 |
| `test_oidc.py` | Discord 登录 | providers 含 discord，授权 URL 正确 |
| `test_oidc.py` | 通用 OIDC | issuer 发现端点，授权 URL 正确 |
| `test_oidc.py` | Discord 首登建号 | exchange 建用户+组织 |
| `test_cli.py` | 登录/建Key/用量/充值 | CLI 对 ASGI app 跑通登录→建 Key→用量→充值→余额 |
| `test_cli.py` | models 命令 | 列出模型并计数 |
| `test_cli.py` | config 命令 | 设置 base_url |
| `test_rerank_responses.py` | rerank 端点 | /v1/rerank 转译+故障转移+成本记账 |
| `test_rerank_responses.py` | responses 端点 | /v1/responses 转发并记 usage |
| `test_rerank_responses.py` | rerank 未知模型 404 | 未知模型 404 |
| `test_audio.py` | TTS 返回音频 | /v1/audio/speech 返回二进制 + 计价 |
| `test_audio.py` | STT 转写 | /v1/audio/transcriptions multipart 上传 → 文本 |
| `test_audio.py` | TTS 未知模型 404 | 未知模型 404 |
| `test_video.py` | 视频生成 | /v1/videos/generations 转发+计价 |
| `test_video.py` | 视频未知模型 404 | 未知模型 404 |
| `test_channel_health.py` | 通道测试成功 | test 端点连通 → status=active |
| `test_channel_health.py` | 通道测试失败 | test 端点报错 → status=error |
| `test_channel_health.py` | 故障自动标记 | 失败通道 status=error，成功通道 active |
| `test_channel_health.py` | 鉴权错误自动禁用 | 401/403 且开关开时自动 enabled=false |
| `test_playground.py` | 站内试聊 | /orgs/{id}/playground/chat 走隐藏 Key，Key 列表不显示 |
| `test_playground.py` | 需成员身份 | 非成员 403 |
| `test_ip_whitelist.py` | IP 白名单放行/拦截 | 命中 IP/CIDR 放行，其它 403 |
| `test_ip_whitelist.py` | 无白名单不限 | 未设白名单任意 IP 放行 |
| `test_ip_whitelist.py` | 入口也校验 | Anthropic 入口同样校验 IP |
| `test_metrics.py` | /metrics 暴露 | Prometheus 格式端点 |
| `test_metrics.py` | 请求后指标递增 | 调用后 tr_requests_total/tr_tokens_total 出现 |
| `test_aliases.py` | 别名 CRUD + 路由 | 建别名后用别名调用透明改写到目标模型 |
| `test_aliases.py` | 目标不存在 404 | 目标模型不在目录 404 |
| `test_aliases.py` | 需超管 | 普通用户 403 |
| `test_price_multiplier.py` | 组织倍率计费 | 设 2× 后成本按倍率折算 |
| `test_price_multiplier.py` | 需超管 | 普通用户设倍率 403 |

## 手动集成测试

### 1. 启动服务

```bash
cd backend
cp .env.example .env  # 填入测试用的 GEMINI_API_KEY 和 ADMIN_TOKEN
uv run uvicorn app.main:app --reload
```

### 2. 创建 API Key

```bash
curl -X POST http://localhost:8000/admin/keys \
  -H "Authorization: Bearer your-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"name": "test-app", "max_total_tokens": 100000, "max_calls": 50}'
# 保存响应中的 key 字段
```

### 3. 调用代理接口

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer tum_xxxx..." \
  -H "Content-Type: application/json" \
  -d '{"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "hello"}]}'
```

### 4. 查看用量

```bash
curl http://localhost:8000/admin/stats/overview \
  -H "Authorization: Bearer your-admin-token"
```

### 5. 测试配额拒绝

创建一个 `max_calls=1` 的 Key，调用两次，第二次应返回 HTTP 429。

### 6. 测试 RPM 限速

创建一个 `max_rpm=2` 的 Key，1 分钟内发送 3 次请求，第 3 次应返回 HTTP 429。

### 7. 迁移验证（P0 引入 Alembic）

```bash
cd backend
# 全新库：直接升到最新
DATABASE_URL="sqlite+aiosqlite:////tmp/mig.db" uv run alembic upgrade head
# 已有部署（此前由 create_all 建库）：先打基线戳再升级
uv run alembic stamp 001 && uv run alembic upgrade head
# Seed 目录与默认组织（幂等，可重复执行）
uv run python -m scripts.seed
```

## 新增功能时的测试规范

1. 改代码前先跑 `uv run pytest`，确认基线全绿
2. 新增功能同步在对应 `tests/` 文件中添加测试用例
3. 改完再跑一遍，确认无回归
4. 在本文件中记录新增的测试用例
