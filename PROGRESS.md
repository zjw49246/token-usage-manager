# 经验教训沉淀

## 并发下配额被绕过 + 记账竞态崩溃（丢用量）

**问题**
- 配额检查读 `usage_summary`，而调用次数在响应结束后才由后台 `asyncio.create_task` 异步写回。
  并发/突发请求在计数落库前全部读到旧值 → 集体通过。实测：`max_calls=1` 并发 20 次，20 次全放行。
- `record_usage` 的 upsert 是「先 SELECT 再 INSERT」，并发首次记账撞 `UNIQUE constraint failed`。
  异常又被 fire-and-forget 的 task 吞掉 → 用量静默丢失。实测：并发 10 次记账，9 次 IntegrityError。

**如何解决**
- 调用次数改为**请求前原子预扣**：`UPDATE usage_summary SET total_calls = total_calls + 1
  WHERE api_key_id = :id AND total_calls < :max_calls`，用 `rowcount == 0` 判定是否超限。
- summary 行用 `INSERT ... ON CONFLICT DO NOTHING` 幂等创建，消除「先查再插」竞态。
- token 累加改为原子表达式 `total_tokens_used = total_tokens_used + :n`，`record_usage` 不再重复计数。
- RPM 检查移到预扣之前，避免被限速拒绝的请求白白消耗一次调用额度。
- 先写复现测试（旧代码 `assert 20 == 3` 红 + IntegrityError），修复后全绿。

**以后如何避免**
- 涉及「配额/额度」的计数，一律在动作**发生前**用带条件的原子 UPDATE 抢占，不要「事后异步记账」。
- upsert 用数据库原生的 `ON CONFLICT`，不要在应用层做 check-then-insert。
- fire-and-forget 的后台 task 不能承载「一致性关键」的写入（异常会被吞、进程重启会丢）。

**commit**: 1558069（fix-concurrent-quota-race 分支）

## token-router 改造 P0：Alembic + 新表落地

**遇到的问题**
- 项目此前用 `create_all` 裸奔建库，给已有表加列（org_id/cost_usd）无法自动生效 → 必须引入 Alembic。
- SQLite 的 batch 模式下，`add_column` 带**内联 ForeignKey** 会产生未命名约束，报
  `ValueError: Constraint must have a name` 且迁移中途失败。
- litellm.model_cost 有 2929 条目，直接全灌目录会混入 ft:/audio/日期快照等长尾垃圾。

**如何解决**
- 双迁移策略：001 基线（原 3 表）+ 002 P0 变更；已有部署 `alembic stamp 001` 后升级；
  测试/新环境仍走 create_all（验证过两条路径产出的 schema 完全一致）。
- batch 加列一律裸 `sa.Column`（不带内联 FK），SQLite 本就不强制 FK，约束保留在模型层。
- seed 用 mode=chat + 主流 7 家 provider + 正则排除长尾，精选出 171 个模型；
  火山 Ark 的 DeepSeek 遗留命名（deepseek-v3-250324 等）手工补价保证行为不变。
- seed 全程幂等（存在即跳过），重复执行 +0。

**以后如何避免**
- 涉及 schema 演进的项目，第一时间引入迁移工具，不要等要加列了才补。
- SQLite + Alembic 记住两条：`render_as_batch=True`、batch 内不用内联 FK。
- 大表灌数据先想清楚「收录标准」，白名单 + 排除模式，别图省事全量灌。

**commit**: 98c5b50（feat/token-router-p0 分支）

## token-router 改造 P1：LiteLLM 内核替换硬编码路由

**遇到的问题**
- P0 seed 把火山 Ark 的 DeepSeek 遗留模型映射到了 `deepseek/deepseek-chat`（官方 api.deepseek.com），
  但现部署实际打的是火山 Ark（base/模型名都不同）——直接上线会**悄悄改变行为**。
- 后台记账 task 直接用 `AsyncSessionLocal`（不走 get_db 依赖注入），测试时写进了真实数据库文件，
  测试读内存库读不到记录。
- `max_cost_usd` 在 models 层加了列，但 schemas.py 没加字段 → 建 Key 时被 pydantic 静默丢弃，
  限额形同虚设（测试 429 变 200 才暴露）。

**如何解决**
- Ark 建成独立供应商 `volcengine-ark`（openai 兼容 + api_base），遗留模型 litellm_model 用
  `openai/{原模型名}` 直通，模型名原样传上游，行为与旧版完全一致。
- conftest 模块级把 `services.router.AsyncSessionLocal` 重定向到测试会话工厂。
- schemas 的 Create/Update/Out 全链路补 `max_cost_usd` / `cost_usd` / `total_cost_usd` 字段。

**以后如何避免**
- 换路由内核时，先枚举**现部署实际在用的每一个模型的完整调用路径**（base/凭证/模型名三元组），
  逐一确认新路径等价，再谈重构。
- 绕过依赖注入的资源（全局 session 工厂等）要在 conftest 里显式重定向，并写一条注释说明为什么。
- 加列必须全链路检查：model → schema(Create/Update/Out) → router 赋值 → 测试断言，缺一环就是静默丢字段。

**commit**: b16a8f3（feat/token-router-p1-litellm-core 分支）

## token-router 改造 P2a：多租户后端（JWT + 组织 + RBAC）

**遇到的问题**
- `passlib[bcrypt]` 与 bcrypt 4.x 不兼容：passlib 1.7.4 读 `bcrypt.__about__.__version__` 报
  `AttributeError`，导致后端加载失败、密码校验全挂。
- 默认 JWT 密钥太短（20 字节），pyjwt 抛 `InsecureKeyLengthWarning`（<32 字节不达 SHA256 要求）。

**如何解决**
- 弃用 passlib，直接用 `bcrypt.hashpw/checkpw`，并显式处理 72 字节上限（截断）。
- 默认 jwt_secret 换成 ≥32 字节占位串，`.env.example` 注明生产用 `openssl rand -hex 32`。

**以后如何避免**
- passlib 已多年不更新，新项目直接用 bcrypt/argon2 原生库，别引 passlib。
- 密钥类默认值就按算法最低长度给，避免「示例值」触发安全警告或被直接带上生产。

**commit**: 见本分支（feat/token-router-p2a-multitenant-backend）

## token-router 改造 P3：三入口方言翻译

**遇到的问题 / 关键决策**
- 三入口（OpenAI/Anthropic/Gemini）若各写一套「调 LiteLLM + 记账」会三份重复且记账口径易漂移。
- Gemini 的 action 在 path 里（`models/{m}:generateContent`），需要 FastAPI 路由能识别 `:action` 后缀。
- 三家 SDK 鉴权头不同：OpenAI/Anthropic 用 Bearer、Anthropic 还用 x-api-key、Gemini 用 x-goog-api-key/?key。

**如何解决**
- 把路由核心抽成 `acompletion_once` / `aiter_openai_chunks`（只产出 OpenAI 规范结果 + 统一在 finally 记账），
  三入口的方言层只做「请求方言→OpenAI」和「OpenAI→响应方言」纯翻译，零重复记账逻辑。
- FastAPI 路由 `"/models/{model}:generateContent"` 字面后缀可用（Starlette 正则 `[^/]+` 会回溯匹配尾部字面量）。
- `get_api_key_flexible` 依赖从 Bearer/x-api-key/x-goog-api-key/?key 多来源取 Key，兼容三家 SDK 习惯。
- 流式各写一套 SSE 事件映射（Anthropic 的 message_start/content_block_delta/...；Gemini 的 alt=sse 风格）。

**以后如何避免**
- 多入口/多协议一律「单一核心 + 边缘翻译」，绝不让记账/配额逻辑散落到每个入口。
- 覆盖外部 API 兼容层时，用 mock 上游的方式对「翻译正确性」做单测（形状/字段/usage），不依赖真实上游。

**commit**: 见本分支（feat/token-router-p3-tri-ingress）

## token-router 改造 P4：额度计费 + 模型对比页

**要点 / 决策**
- 消费扣减发生在后台记账 task（`record_usage`）里，与 token/cost 累加同一事务；
  用 `apply_credit`（原子 UPDATE 余额 + 写台账）串在 commit 前，避免半更新。
- 欠额闸门放在 `check_quota`（请求前），余额<=0 返回 402；但只对「归属组织」的 Key 生效，
  `/admin/keys` 建的无 org Key 不受影响（否则平台冒烟/存量测试会被拦）。
- 新组织赠送 `welcome_credit_usd`（默认 $5）保证开箱即用，不用先充值；可用 `enforce_credit_balance=false` 全局关闸。

**以后如何避免**
- 余额/台账这类「钱」的写入，一律走单一 `apply_credit` 入口（原子改额 + 记流水），
  不要在多处散写 UPDATE，否则余额和台账会对不上。
- 加「拒绝类闸门」时先想清楚豁免范围（此处：无 org 的平台 Key 必须豁免），并用测试固定这条边界。

**commit**: 见本分支（feat/token-router-p4-billing-catalog）
