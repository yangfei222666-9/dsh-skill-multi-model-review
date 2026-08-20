# DSH Skill: multi-model-review

Gives a DeepSeek Harness agent a **four-view candidate review** capability: Zhipu GLM / Claude (headless CLI, relay-compatible) / Google Gemini / Codex review your growth artifacts and return a structured verdict JSON, with token and cost usage recorded.

- **Zero third-party dependencies** (Python standard library); runs on any `python3`
- Results are only ever `candidate_review_input` — they never replace local evidence. This is a design discipline, not a slogan.

## Install (DSH)

```bash
mkdir -p "$DSH_HOME/skills/multi-model-review"
cp SKILL.md multi_model_review.py "$DSH_HOME/skills/multi-model-review/"
# or symlink (the DSH skill system hot-discovers skills):
# ln -sfn "$(pwd)" "$DSH_HOME/skills/multi-model-review"
```

Once installed, the agent auto-loads this skill for matching tasks; you can also ask the agent directly to "use the multi-model-review skill".

## Configure

```bash
cp providers.env.example providers.env
# fill ZHIPUAI_API_KEY / GEMINI_API_KEY / CLAUDE_RELAY_KEY (+BASE for relays)
```

## Run

```bash
python3 multi_model_review.py --env providers.env --out ./reviews my-lesson.md my-rule.md
```

## Typical scenarios

- Weekly self-evolution ritual: run one review round before the ritual, then accept/reject each suggestion after individual review
- Suspecting a lesson of over-generalizing from a single sample: send it to four reviewers for challenge
- Portfolio review: treat the four opinions as external candidate feedback (not human validation — candidates only)

## Notes

- If a Claude relay performs client-fingerprint checks, only the real Claude Code CLI channel passes — this script's Claude channel is exactly that headless CLI mode
- A single Claude round costs what the relay charges (commonly $0.3–1/round); glm/gemini use free quotas, codex uses the local Pro membership
- `CLAUDE_RELAY_BASE` must not include `/v1` (the CLI appends `/v1/messages` itself); Gemini requires `max_completion_tokens` (already built in)

## Development

```bash
python3 -m unittest discover -s tests -v
```

MIT License

## Disagreement policy (not majority vote)

All four reviewers are LLMs and may share blind spots — agreement does not create truth. When verdicts conflict: (1) every suggestion is reviewed one by one against local evidence; (2) adoption requires a concrete change plus a receipt; (3) rejections are logged with reasons. Local evidence always wins over quorum.

## Configuring Codex

Codex runs through the local Codex CLI (`codex exec`) using the machine's Pro membership; no key is stored by this project. If Codex is unavailable, the pipeline records a transport failure and the remaining three channels still run.

## Failure handling

A provider transport failure (401/403/404/timeout) is recorded in the review file and provider-usage ledger; the run continues with the remaining providers and never fails the whole review silently.
