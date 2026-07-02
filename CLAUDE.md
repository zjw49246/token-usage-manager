# token-usage-manager — 项目指南

> **重要：Claude 必须自主维护本文件。** 架构或约定变化时更新，保持简洁。

## 架构与改造方向

本项目已从「Gemini/DeepSeek 用量代理」改造为 TokenRouter——多供应商 AI 网关
（P0~P5 六期完成）。改造历程见 `docs/TOKEN_ROUTER_TRANSFORM.md`。
产品形态：三入口协议（OpenAI/Anthropic/Gemini）+ LiteLLM 内核 + 多租户 RBAC + 预付费计费 + 模型目录。

- **后端**：FastAPI + SQLAlchemy 2.0 async + SQLite(WAL)，`uv` 管理依赖；`backend/app/`
- **迁移**：Alembic（`backend/alembic/`）。已有部署先 `alembic stamp 001` 再 `alembic upgrade head`；
  测试/全新开发环境由 `create_all` 直接建全量 schema
- **Seed**：`uv run python -m scripts.seed` 灌供应商注册表 + 模型目录（价格来自 litellm.model_cost）+ 默认组织回填
- **数据模型**（P0 后）：多租户（organizations/users/memberships/credit_transactions）+
  平台目录（providers/model_catalog）+ 原有（api_keys/usage_records/usage_summary，已加 org_id/cost 列）
- **路由内核**（P1 后）：`services/router.py` 用 LiteLLM 数据驱动路由（model_catalog → litellm_model
  + provider.api_base + 凭证 env），旧 `services/proxy.py` 已删除；成本按目录单价核算并原子累加；
  Vertex AI 模式暂不支持（当前部署未使用，需要时经 litellm vertex_ai 前缀恢复）。
  核心暴露 `acompletion_once` / `aiter_openai_chunks`（产出 OpenAI 结果 + 统一记账），供三入口复用
- **三入口协议**（P3 后）：`dialects/{anthropic,gemini}.py` 做方言↔OpenAI 双向翻译，
  `routers/ingress_{anthropic,gemini}.py` 暴露 `POST /v1/messages`（Claude）和
  `/v1beta/models/{m}:generateContent[|:streamGenerateContent]`（Gemini，含流式）；
  `dependencies.get_api_key_flexible` 兼容 Bearer / x-api-key / x-goog-api-key / ?key
- **鉴权**（P2 后）：三平面——① 用户 JWT（`/auth` 注册登录，`services/user_auth.py` bcrypt+pyjwt）；
  ② 组织 RBAC（`dependencies.require_role`，member<admin<owner，超管视作 owner）；
  ③ 代理 API Key（`tum_`，归属 org）+ 平台超管 `ADMIN_TOKEN`（`/admin`）。
  org 隔离 API 在 `routers/orgs.py`（Key/用量/统计强制按 org_id 过滤）
- **计费**（P4 后）：`services/credits.py` 的 `apply_credit` 原子改余额+写台账；新组织赠送
  `welcome_credit_usd`；`record_usage` 按成本扣减组织余额并记 usage 台账；`check_quota` 在
  `enforce_credit_balance` 下余额<=0 返回 402；`/orgs/{id}/credits` GET 查余额+流水、POST 充值(owner)
- **前端**（P2b/P4 后）：React18 + Vite + antd5，build 后由 FastAPI 托管；`frontend/`。
  JWT 会话（`stores/authStore.js`）+ 登录注册页 + 顶栏组织切换器 + 成员管理页；
  数据页走 `/orgs/{currentOrgId}/*`；模型目录对比页（Models）+ 额度计费页（Billing）；旧 adminStore 已删

## Git 信息

- Remote: https://github.com/zjw49246/token-usage-manager
- 默认分支: main

## 任务生命周期

你收到任务后，按以下 9 步流程自主完成：

1. **领取任务** — 你已被分配任务，阅读本文件和项目代码理解上下文
2. **创建工作区**:
   - `git fetch origin`（如有 remote）
   - `git worktree add -b task-<简短描述> .claude-manager/worktrees/task-<简短描述> origin/main`
   - 进入 worktree 目录工作（后续所有操作在 worktree 中）
   - 如果 worktree 创建失败，直接在当前分支工作
3. **实现功能** — 编写代码，确保可运行
4. **提交代码** — `git add` + `git commit`，commit message 简洁描述改动
5. **Merge + 测试**:
   - `git fetch origin && git merge origin/main`（集成最新代码，如有 remote）
   - 运行测试（如有测试命令）
6. **自动合并到 main**（如有 remote）:
   - `git fetch origin main`
   - `git rebase origin/main`，如果冲突则自行 resolve
   - 如果成功：`git checkout main && git merge <task-branch> && git push origin main`
   - 如果这一步有任何失败，退回到步骤 5 重试
   - （纯本地项目跳过本步）
7. **标记完成** — 更新文档（必须在清理之前，防止进程被杀时状态丢失）
8. **清理** — 回到项目根目录:
   - `git worktree remove .claude-manager/worktrees/<worktree名>`
   - `git branch -D <task-branch>`
   - 如有 remote: `git push origin --delete <task-branch>`
9. **经验沉淀** — 在 PROGRESS.md 记录经验教训（可选）

### 冲突处理

rebase 发生冲突时：
1. 查看冲突文件: `git diff --name-only --diff-filter=U`
2. 逐个解决冲突
3. `git add <resolved-files> && git rebase --continue`
4. 如果无法解决: `git rebase --abort`，退回步骤 5

### 状态判断

- 通过 `git remote -v` 判断是否有 remote
- 有 remote → 必须完成步骤 6（merge + push）
- 无 remote → 跳过步骤 5 的 fetch、步骤 6 和步骤 8 的远程分支删除

## 文件维护规则

> **以下文件都由 Claude Code 自主维护，每次功能变更后必须同步更新。**

- **CLAUDE.md**（本文件）：架构、约定、关键路径变化时更新，只改变化的部分，保持简洁
- **README.md**：面向用户的文档，功能、使用流程变化时同步更新，保持与实际代码一致
- **TEST.md**：测试指南，新增功能时同步添加测试用例和文档
- **PROGRESS.md**：见下方「经验教训沉淀」

## 测试规范

**开发时必须主动使用测试，不是事后补充！**

- **改代码前**：先跑测试，确认基线全绿
- **改代码后**：再跑一遍确认无回归
- **新增功能**：同步新增测试用例，更新 TEST.md
- **修 bug**：先写复现 bug 的测试（红），修复后确认变绿

## 经验教训沉淀

每次遇到问题或完成重要改动后，要在 PROGRESS.md 中记录：
- 遇到了什么问题
- 如何解决的
- 以后如何避免
- **必须附上 git commit ID**

**同样的问题不要犯两次！**

## 注意事项

- 在 worktree 中工作时，不要切换到其他分支
- 完成任务后确保代码可运行、测试通过
