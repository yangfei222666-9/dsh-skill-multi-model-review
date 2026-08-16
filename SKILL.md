---
name: multi-model-review
description: 多模型候选评审管线:调度智谱 GLM / Claude(CLI 无头,可走中转)/ Gemini(OpenAI 兼容口)/ Codex 四视角评审成长 artifact(教训/规则/审计板),输出严格 JSON(verdict/strengths/risks/suggestions/cannot_claim),结果只作 candidate_review_input,永不替代本地证据。适用:用户要求外部交叉评审、周期性仪式前自动评审、怀疑某条结论过度推广时。
whenToUse: 需要对 agent 成长 artifact(教训库/规则库/成长审计)做多模型交叉评审时;或需要"多视角 challenge"而非单一模型意见时。
---

# 多模型候选评审(四视角)

## 前置

1. 复制 `providers.env.example` 为 `providers.env`,填入至少两把 key(智谱 / Gemini / Claude 中转任一组合;Codex 通道无需 key,走本地 CLI 额度)
2. Claude 通道需要已安装 Claude Code CLI(`~/.local/bin/claude`,可 `CLAUDE_BIN` 覆盖);Codex 通道需要 ChatGPT.app 内置 codex(可 `CODEX_BIN` 覆盖)
3. 零第三方依赖(urllib 标准库),python3 直接跑

## 入口

```bash
python3 multi_model_review.py --env providers.env --out ./reviews 目标1.md 目标2.md
```

- 不传目标文件时,自动找 `$ARTIFACT_DIR` 下的 LESSONS.jsonl / rules/operator-rules-v1.md / GROWTH.md
- 输出:`reviews/reviews-<时间戳>.jsonl`(verdict + 四段建议)+ `provider-usage.jsonl`(token 与成本账本)
- key 缺失的 provider 自动跳过;401 立即停,403/404/空回复走模型降级链

## 铁律

1. provider 输出 = candidate_review_input,不是 truth;四家都说好 ≠ 成立
2. 只发送 artifact 文本;绝不发送密钥
3. 每条建议逐条复核:采纳 → 实际改动 + 留痕;驳回 → 写理由
4. verdict ∈ {support, mixed, challenge} 只做定级参考

## 已知坑(实测结论,rc 环境 2026-08)

- Claude 中转若只认 Claude Code CLI 指纹:本通道天然免疫(curl/httpx 反而过不了)
- `CLAUDE_RELAY_BASE` 不要带 `/v1`(CLI 自己拼 `/v1/messages`)
- Gemini 需 `max_completion_tokens`(脚本已内置);部分智谱账号对最新模型 403 无权 → 自动降级
- 后台跑加 `python3 -u` 保持实时输出
