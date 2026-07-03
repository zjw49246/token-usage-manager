# 经验教训沉淀

## 去商业化：移除货币化/促销，保留功能性

**背景**：产品重新定位为纯功能性网关，去掉之前做的所有货币化/促销功能。

**移除**（商业性）：Stripe 支付（services/payments.py、routers/billing.py、/credits/checkout、stripe 依赖）、
预付费额度钱包（services/credits.py、apply_credit、credit_transactions 表、organizations.credit_balance_usd、
welcome_credit_usd 赠送、enforce_credit_balance 的余额<=0→402 闸门、手动充值 /credits）、
组织价格倍率（price_multiplier、PATCH /pricing、record_usage 里的倍率折算）、前端 Billing 页 + 导航项。

**保留**（功能性，边界判断）：`cost_usd` 的核算/记账/展示是**观测**能力，不是计费——保留；
成本作为**配额上限**（Key 的 max_cost_usd、成员 budget_usd→429）是功能性限额（等价于 token 配额），保留；
模型目录价格是信息展示，保留。核心判据：**「记录/限制成本」是功能，「收钱/扣余额/加价」才是商业**。

**要点**
- 删列/删表用 alembic 013（batch_alter_table drop_column + drop_table）；因 init_db 走 create_all，
  已部署库不会自动掉列（无害），但迁移链要补齐，且验证 `alembic upgrade head` 后 organizations 只剩 4 列、
  credit_transactions 消失，与模型 create_all 一致。
- 删依赖要顺藤摸瓜清 import：quota.py 去掉 apply_credit 后 settings/Organization 都变成未用，一并删；
  orgs.py 去掉 pricing 后 require_superadmin 未用，一并删——留着死 import 不报错但脏。
- 测试从 104→94（删 test_billing/test_stripe/test_price_multiplier 共 10 例），改 test_p0_schema/test_cli
  里对 credit_transactions/topup/balance 的引用。前端 build 通过确认无残留 import。

**以后如何避免**
- 做「功能 vs 商业」切割时，先立判据（记录/限制=功能，收费/扣费=商业），再逐特性归类，避免误删观测能力。

**commit**: 见本分支（feat/remove-commercial）

## token-router 改造 P15-P17：补全端点矩阵（rerank/responses/audio/video）

**要点**
- litellm 对每种端点都有对应异步函数（arerank/aresponses/aspeech/atranscription/avideo_generation），
  统一走 `_route_litellm_json`（JSON 类）或专用二进制/multipart 处理；成本用 `litellm.completion_cost` 兜底
  （非 token 计价的 audio/video/rerank 也能算出真实成本）。
- 之前 seed 的 EXCLUDE_PATTERN 排除了 audio/whisper/tts，要开这些端点必须放开；
  同时给 catalog 的 mode 增加 audio/video/rerank，前端 Models 页同步加类型标签与筛选。
- audio 特殊：TTS 返回二进制（按 response_format 设 media_type），STT 是 multipart 上传（FastAPI File/Form）。

**以后如何避免**
- 网关补端点时，先确认底层 SDK（litellm）是否已有对应函数，有就统一封装、只处理输入输出差异（JSON/二进制/multipart）。
- 数据 seed 的排除规则会悄悄挡掉后续要用的模型类别，扩端点时记得回头检查 EXCLUDE。

## token-router 改造 P11：第三方登录 SSO（GitHub/Google）

**要点 / 决策**
- provider 注册表（authorize/token/userinfo URL + scope），未配 client_id 的 provider 自动不启用；
  前端据 `/auth/oauth/providers` 动态渲染登录按钮，无配置就不显示。
- 抽出 `provision_user`（建号+个人组织+赠额度），注册与 SSO 首登共用；SSO 首登按邮箱 find-or-create，
  已存在则直接登录同账号（避免重复建号/多组织）。
- GitHub 的主邮箱可能不在 /user 里，需另查 /user/emails 取 primary+verified。
- state 存 sessionStorage 前端比对做 CSRF 防护（SPA 无服务端 session，故客户端校验）。

**以后如何避免**
- 多 provider 的 OAuth 用「注册表 + 统一 exchange」，各家差异（如 GitHub 邮箱另取）收敛到少量分支。
- 用户建号逻辑（含建组织/赠额度）要抽成单一入口，任何新登录方式都复用，避免各处漏建组织。

**commit**: 见本分支（feat/token-router-p11-sso）

## token-router 改造 P10：成员级预算

**要点 / 决策**
- tokenrouter 宣传「成员/团队/部门」三级预算。我们已有组织级余额 + 每 Key 成本上限，
  本期只做**成员级**（每用户在组织内累计消费上限）；团队/部门需引入子分组结构，作为更大改动单列。
- 成员消费 = 该用户在本组织创建的所有 Key 的 usage_summary.total_cost 之和（`created_by_user_id` 关联），
  在 check_quota 里聚合比对 membership.budget_usd，超则 429。
- 注意豁免：`/admin/keys` 建的无 org/无 created_by 的 Key 不受成员预算约束，避免影响平台冒烟。

**以后如何避免**
- 复刻"看起来是一个功能"的东西前，先拆清它的层级（成员/团队/部门是三层），
  按现有数据模型能低成本覆盖哪层就先做哪层，缺结构的层级明确标注为独立改动，别硬凑。

**commit**: 见本分支（feat/token-router-p10-member-budget）

## token-router 改造 P9：Stripe 支付

**要点 / 决策**
- Checkout + webhook 异步入账：前端发起 checkout → Stripe 支付 → webhook `checkout.session.completed` → 入账。
- **幂等**：以 Stripe 的 payment_intent/session id 为 `ref`，入账前查 credit_transactions 是否已有同 ref 的 topup，
  避免 webhook 重复投递（Stripe 会重试）导致重复加钱。
- **金额以 amount_total（实付）为准**，不信任前端/metadata 里的金额，防篡改。
- webhook 端点无鉴权但**验签**（stripe 签名），且 Stripe 未配置时整套支付功能关闭、手动充值仍在。

**以后如何避免**
- 任何异步支付回调都要幂等（外部会重试）+ 以支付方的实付金额为准 + 验签，三者缺一都会出资损或安全问题。
- 第三方能力做成「可选开关」：未配置时优雅降级到内置方案（手动充值），不要让缺配置直接 500。

**commit**: 见本分支（feat/token-router-p9-stripe）

## token-router 改造 P8：补齐端点类型（embeddings / image）

**要点 / 决策**
- 抽出通用故障转移执行器 `_try_failover(routes, fn, extract_usage, extract_cost)`，
  embeddings/images 复用同一套「逐通道尝试 + 记账」，避免每种端点重写重试逻辑。
- 计价分流：embeddings 按 token（复用 compute_cost）；image 按张（`cost_override = n × image_price`）。
  为此给 `_save_usage_bg` 加 `cost_override`，非 token 计价也能统一记账。
- litellm 图像模型价格是「按像素/尺寸前缀命名」的长尾（键形如 `1024-x-1024/dall-e-2`），
  直接灌会污染目录且 litellm_model 无效——只收录有 `output_cost_per_image` 且键无 `/` 的干净名，
  主流 dall-e-3/gpt-image-1 手工补每张价。

**以后如何避免**
- 多种"同构但计价不同"的端点，先抽公共执行器，把差异收敛到几个小回调（usage/cost 提取），别整段复制。
- 灌第三方价格表前先看清它的键命名规律，长尾/变体命名要用白名单或规整，别直接全量入库。

**commit**: 见本分支（feat/token-router-p8-endpoints）

## token-router 改造 P7：响应缓存（去重复用 + 命中计费）

**要点 / 决策**
- 只缓存**非流式** chat（流式重放复杂、收益低）；缓存键 = 请求内容（model+messages+采样参数）的 sha256，
  全局内容寻址、跨租户去重省钱；命中仍按 org 记账但成本 × `cache_hit_cost_multiplier`（默认 0=免费），provider 记 "cache"。
- 缓存后端抽象：默认进程内内存（带 TTL），配 `REDIS_URL` 则用 Redis（多副本共享）；redis 延迟导入，未装也能跑内存。
- **测试隔离坑**：缓存默认开启后，很多测试用相同请求体，会跨测试命中导致上游 mock 计数错乱。
  解决：conftest 的 autouse fixture 里 `reset_cache()`，每个测试用全新缓存。

**以后如何避免**
- 引入全局共享状态（缓存/连接池/单例）后，测试要有重置钩子，否则测试间会经缓存互相污染。
- 缓存"相同请求"要精确定义键字段；把 temperature/max_tokens 等采样参数纳入键，避免不同参数复用同一结果。

**commit**: 见本分支（feat/token-router-p7-caching）

## token-router 改造 P6：负载均衡 + 故障转移（多通道）

**要点 / 决策**
- 路由核心从「单 route」改为「有序 route 列表」，逐条尝试：非流式可完整故障转移；
  流式只在**建流前**可转移（一旦产出 chunk 就不能回滚已发内容）——这是流式 failover 的通行边界。
- 为向后兼容，`resolve_routes` 在无通道配置时回退到 P1 的单路由（catalog+provider），
  存量 44 个测试全部无改动通过。
- 记账口径不变：cost 用 model_catalog 的价格（与通道无关），只把 provider 记成实际成功的通道供应商。
- 通道管理是平台级（超管），但 UI 用 JWT——于是加 `require_superadmin` + 用 ADMIN_TOKEN 的
  `POST /admin/superadmin` bootstrap，避免 UI 依赖静态 token。

**以后如何避免**
- 引入「多候选 + 重试」时，先界定清楚哪些阶段可安全重试（幂等/未产出副作用前），别在已向客户端输出后重试。
- 平台级功能若要在用户 UI 里操作，鉴权要统一到用户身份体系（超管标志），并提供 bootstrap 路径。

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

## token-router 改造 P5：品牌收尾 + 容器开箱即用

**要点**
- 品牌统一为 TokenRouter：FastAPI title、index.html、包名（tokenrouter / tokenrouter-frontend）、README 重写。
- 容器/首次启动自动 seed 模型目录（`main.py:_seed_if_empty`，幂等，目录为空才灌），
  避免新部署 `/v1/models` 为空、要手动跑 seed。
- 修 docker-compose 的坑：原来强制挂载 `./backend/credentials.json:ro`（Vertex 用），
  文件不存在会让 `docker compose up` 失败或误建目录——Vertex 已不支持，直接删除该挂载。
- 改 pyproject `name` 后 uv.lock 的项目名会变，必须 `uv lock` 重新生成，否则 Docker 里 `uv sync --frozen` 会失败。

**以后如何避免**
- 容器镜像要「开箱即用」：初始化数据（seed）应在应用启动时幂等完成，不要依赖使用者手动跑脚本。
- compose 里挂载宿主机文件（非目录）且该文件可能不存在时，务必设为可选或去掉，否则破坏一键启动。

**commit**: 见本分支（feat/token-router-p5-rebrand）
