# Midnight Companion(工作名)

深夜育儿陪伴热线 —— voice-first AI companion for burned-out parents of infants.
凌晨三点宝宝哭闹时,一键「拨通」一个温柔的夜班护士声音(或随时切回文字),它了解你的宝宝(月龄、喂养方式、今晚发生了什么),给出临床审核过的可信建议,并在真正危险时明确升级(一键拨打医生/911)。**用户是家长,宝宝是上下文。**

- 设计规格(权威事实源):[docs/DESIGN.md](docs/DESIGN.md)
- 进度事实源(随阶段更新):[docs/PROGRESS.md](docs/PROGRESS.md)
- 前后端契约:[CONTRACTS.md](CONTRACTS.md)

## Stack

| 层 | 技术 |
|---|---|
| Frontend | Next.js 16 (App Router) PWA, Tailwind, 暗夜主题, `frontend/` |
| Backend | FastAPI + uv (Python 3.12), 全部 AI 与安全逻辑, `backend/` |
| DB/Auth | Supabase (Postgres + RLS + magic link/Google);schema 由 Alembic 管理, `backend/alembic/` |
| AI | Claude API (claude-sonnet-5 主对话, haiku 分诊分类器) |
| Voice | Vapi (Phase 2: custom-LLM 指向 FastAPI, STT/TTS/打断托管) |

## Local dev

```bash
supabase start                                   # local Postgres + Auth + Studio
cd backend && cp .env.example .env
cd backend && uv run alembic upgrade head        # apply DB migrations (Alembic, 同其他项目惯例)
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd frontend && cp .env.example .env.local && pnpm install && pnpm dev
```

新迁移:`cd backend && uv run alembic revision -m "描述"`(手写 SQL 于 `op.execute`,RLS/触发器不可 autogenerate);回滚:`uv run alembic downgrade -1`。

## Safety architecture (the point of this product)

三层安全体系,失效方向永远保守:
1. **确定性红旗规则引擎**(纯代码,age-aware,<1ms,不依赖模型)
2. **并行 LLM 分诊分类器**(2s 超时静默降级)
3. **Prompt 硬规则 + 输出过滤**(禁药物剂量/禁劝阻就医/禁违反安全睡眠 ABC)

三个信号源取最严;`<triage/>` 前导标签协议见 CONTRACTS.md;黄金安全测试集在 `backend/tests/evals/`,红旗召回 >99% 是上线硬门槛,临床审核签字后才可发布。

## Tests

```bash
cd backend && uv run pytest -q          # unit + offline safety suite (no network)
cd backend && uv run pytest -m eval_live  # live model evals (needs ANTHROPIC_API_KEY)
cd frontend && pnpm build
```
