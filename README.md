# DSH Skill: multi-model-review

> **痛点**:单一模型评审自己的产出,等于自我背书。
> **解法**:GLM / Claude / Gemini / Codex 四视角独立评审,输出带 verdict 的 JSON + token 成本记账;结果只作 `candidate_review_input`,永不替代本地证据。
> **证据**:17 个测试全绿,CI 绿,零第三方依赖。

让 DeepSeek Harness 的 agent 拥有「四视角候选评审」能力:智谱 GLM / Claude(CLI 无头,可走中转站)/ Google Gemini / Codex 四通道评审你的成长 artifact,输出带 verdict 的 JSON,并自动记账 token 与成本。

- **零第三方依赖**(Python 标准库),任何 python3 可跑
- 结果只作 `candidate_review_input`,永不替代本地证据 —— 这是设计纪律,不是口号

## 安装(DSH)

```bash
mkdir -p "$DSH_HOME/skills/multi-model-review"
cp SKILL.md multi_model_review.py "$DSH_HOME/skills/multi-model-review/"
# 或符号链接(DSH 技能系统支持热发现):
# ln -sfn "$(pwd)" "$DSH_HOME/skills/multi-model-review"
```

装好后 agent 在相关任务中会自动加载该技能;也可以直接让 agent 「用 multi-model-review 技能」。

## 配置

```bash
cp providers.env.example providers.env
# 填 ZHIPUAI_API_KEY / GEMINI_API_KEY / CLAUDE_RELAY_KEY(+BASE,中转站用)
```

## 运行

```bash
python3 multi_model_review.py --env providers.env --out ./reviews 我的教训.md 我的规则.md
```

## 典型场景

- 周日自进化仪式:仪式前跑一轮,评审建议逐条复核后采纳/驳回
- 怀疑某条教训"从单次样本过度推广":送四家 challenge
- 求职作品集评审:拿四家意见当外部候选反馈(非真人验证,只是候选)

## 备注

- Claude 中转站若做客户端指纹校验,只有真 Claude Code CLI 通道能过 —— 本脚本的 Claude 通道正是 CLI 无头模式
- 单轮 Claude 成本视中转站计费(常见 $0.3-1/轮);glm/gemini 走免费额度、codex 走 Pro 会员
