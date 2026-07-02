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
