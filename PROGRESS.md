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
