# Progress — Midnight Companion

> 本文件是**进度事实源**,随每个阶段落地即时更新。产品/架构规格见 [DESIGN.md](DESIGN.md)(权威),接口契约见 [../CONTRACTS.md](../CONTRACTS.md)。
> Last updated: 2026-07-25 (branch `feat/phase2-voice`)

## 阶段总览

| 阶段 | 状态 | 证据 |
|---|---|---|
| 0. Monorepo 地基(Next.js 16 + FastAPI + Supabase + Alembic + CI) | ✅ 已合并 | [PR #1](https://github.com/daijun-t18r/babysitter/pull/1),CI 双 job 绿 |
| 1. 安全大脑 + 文字聊天 + SOS | ✅ 已合并 | PR #1;265 离线测试;87 条黄金安全用例;[实机截图](screenshots/) |
| 3. 被动记忆 + 晨间总结 | ✅ 已合并 | PR #1;「未确认永不注入」查询层不变量有路由级测试锁死 |
| 2. Vapi 语音层(代码部分) | ✅ 本分支完成 | 299 后端测试(+34);env-less 前端构建绿;见下文「阶段 2 详情」 |
| 2. 真机 spike(iPhone Safari 延迟/打断/哭声 STT) | ⏸ **等 Vapi 密钥** | 回退契约见 DESIGN.md「Voice 风险契约」 |
| 4a. 上线硬门槛(可做项) | ✅ 本分支完成 | 306 后端测试(+7);离线 SOS service worker(mc-v1 预缓存 /sos+紧急号码,永不缓存 /api);`DELETE /api/v1/me` GDPR 级联删除(admin 失败即 502 零半删)+ 设置页输入 DELETE 确认 |
| 4a. 临床审核签字 | ⏸ **等人选** | 签字对象:分诊表 + knowledge/ 知识包 |
| 4b. 打磨(非阻塞) | ⬜ 未开始 | 暗夜/红光主题细化、动效、文案 |

## 阶段 2 详情(本分支,未合并)

一份大脑、两个传输层已落地:
- `POST /api/v1/voice/session` → ≤15min HMAC 令牌(绑定 user+child)→ Vapi `assistantOverrides.metadata` → `/v1/chat/completions`(OpenAI 兼容流)复用 chat.py 同一安全状态机(规则/标签剥离/剂量过滤/审计/提取)
- Alembic 002:safety_events 加入 Realtime 发布(幂等守卫);通话中紧急/危机卡经 Realtime 复用同一组件
- 前端:通话覆盖层(实时字幕/静音/切文字/挂断)、`@vapi-ai/web` env-gated(未配置时功能整体隐藏)
- 双凭据比较均 `hmac.compare_digest`;dev 匿名模式仍过标签剥离+剂量过滤、零持久化

## 等创始人的事(阻塞项)

1. **Vapi**:控制台建 assistant(custom-LLM URL → 部署后的 `/v1/chat/completions` + `X-Vapi-Secret`);填 `NEXT_PUBLIC_VAPI_PUBLIC_KEY` / `NEXT_PUBLIC_VAPI_ASSISTANT_ID` / `VAPI_SHARED_SECRET`
2. **临床审核人选**(儿医/IBCLC)——4a 硬门槛,签字对象:分诊表 + `backend/app/ai/prompts/knowledge/`
3. **外部访谈**:3 名有 0-12 月宝宝的父母(office-hours 作业,校准 wedge)
4. `ANTHROPIC_API_KEY` 填入 `backend/.env` 后可验证真实流式回复与 live 评测(`pytest -m eval_live`)

## 技术债登记(来自三方结构审计,均不阻塞)

- 中:路由缺 Pydantic response_model;chat.py 550 行待拆(state machine → service 层);前端 triage 聚合逻辑零测试;onboarding 一处直写 Supabase 绕过后端
- 低:TriageLevel 枚举位于 app.ai 层(应下沉 core);messages/events 用 UUIDv4 主键(可换 UUIDv7);列表端点无游标分页

## 决策日志(摘要,完整见 DESIGN.md)

- P1-P7 七条前提(用户是家长/竞品是 ChatGPT/记录是副产品/安全保守失效/接受自然流失/栈锁定/孩子永不直接使用)
- 方案 C+B:Vapi 语音优先 + 记忆大脑,语音是可替换传输层(三条回退:浏览器内运行 → PSTN 热线 → 文字为主)
- 迁移体系:Alembic 手写迁移(同 haus-in-bio 惯例),不用 autogenerate(RLS/触发器不可生成)
