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

**commit**: <见本次提交>（fix-concurrent-quota-race 分支）
