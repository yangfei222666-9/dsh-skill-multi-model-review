#!/usr/bin/env python3
# 多模型候选评审管线 v3.2(社区泛化版,零第三方依赖)
# 用法:python3 multi_model_review.py --env providers.env --out ./reviews 目标1.md 目标2.md
# 四通道:智谱 GLM / Claude(CLI 无头,可走中转)/ Gemini(OpenAI 兼容口)/ Codex(本地 CLI)
# 铁律:provider output = candidate_review_input,不替代本地证据;不发送密钥;输出留痕
import json, os, re, subprocess, sys, datetime, argparse
import urllib.request, urllib.error

MAX_CHARS = 12000
CODEX_BIN_DEFAULT = "/Applications/ChatGPT.app/Contents/Resources/codex"
CLAUDE_BIN_DEFAULT = os.path.expanduser("~/.local/bin/claude")

SYSTEM = """你是候选评审员(candidate reviewer)。评审对象是另一个 AI 值班系统的成长 artifact。
铁律:
- 你的输出是 candidate_review_input,不是 truth,不替代本地证据
- 只基于给定文本评审,不编造被审者没有的行为
- 输出严格 JSON:{provider, verdict, strengths[], risks[], suggestions[], cannot_claim}
- verdict ∈ {support, mixed, challenge}"""

def load_env(path):
    env = {}
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env

def http_post_json(url, headers, body, timeout=60):
    req = urllib.request.Request(url,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code}: {raw[:200]}") from e
    return json.loads(raw)

def post_openai_compat(base, key, model, content, timeout=60, max_out=2000, completion_key="max_tokens"):
    d = http_post_json(f"{base.rstrip('/')}/chat/completions",
        {"Authorization": f"Bearer {key}"},
        {"model": model, "temperature": 0.3, completion_key: max_out,
         "messages": [{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": content[:MAX_CHARS]}]},
        timeout=timeout)
    if "choices" not in d:
        raise RuntimeError(f"响应异常: {json.dumps(d, ensure_ascii=False)[:200]}")
    usage = d.get("usage", {})
    msg = d["choices"][0]["message"].get("content") or ""
    if isinstance(msg, list):
        msg = "\n".join(p.get("text", "") for p in msg if isinstance(p, dict))
    return msg, usage

def call_glm(env, content):
    key = env.get("ZHIPUAI_API_KEY")
    base = "https://open.bigmodel.cn/api/paas/v4"
    models = [m.strip() for m in (env.get("ZHIPUAI_MODEL") or "glm-5,glm-5-turbo,glm-4.6").split(",") if m.strip()]
    last_err = None
    for model in models:
        try:
            text, usage = post_openai_compat(base, key, model, content)
            if not (text or "").strip():
                raise RuntimeError("空回复,换下一模型")
            return text, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), 0.0
        except Exception as e:
            last_err = e
            if "401" in str(e):
                raise
            continue
    raise last_err

def call_gemini(env, content):
    key = env.get("GEMINI_API_KEY")
    base = env.get("GEMINI_BASE") or "https://generativelanguage.googleapis.com/v1beta/openai"
    models = [m.strip() for m in (env.get("GEMINI_MODEL") or "gemini-3.1-pro-preview,gemini-3.7-flash,gemini-2.5-pro").split(",") if m.strip()]
    last_err = None
    for model in models:
        try:
            text, usage = post_openai_compat(base, key, model, content, completion_key="max_completion_tokens")
            if not (text or "").strip():
                raise RuntimeError("空回复,换下一模型")
            return text, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), 0.0
        except Exception as e:
            last_err = e
            if "401" in str(e):
                raise
            continue
    raise last_err

def call_claude_cli(env, content, workdir):
    binpath = env.get("CLAUDE_BIN") or CLAUDE_BIN_DEFAULT
    base = env.get("CLAUDE_RELAY_BASE") or ""
    key = env.get("CLAUDE_RELAY_KEY") or ""
    model = env.get("CLAUDE_RELAY_MODEL") or "claude-opus-4-5"
    prompt = f"{SYSTEM}\n\n被审 artifact:\n\n{content[:MAX_CHARS]}\n\n请严格按上述 JSON 格式输出评审结果,不要使用任何工具。"
    cli_base = base.rstrip("/")
    if cli_base.endswith("/v1"):
        cli_base = cli_base[:-3]  # Claude CLI 自己会拼 /v1/messages
    sub_env = dict(os.environ)
    sub_env["ANTHROPIC_BASE_URL"] = cli_base
    sub_env["ANTHROPIC_AUTH_TOKEN"] = key
    sub_env["ANTHROPIC_MODEL"] = model
    r = subprocess.run(
        [binpath, "-p", prompt, "--max-turns", "1", "--output-format", "json"],
        capture_output=True, text=True, timeout=600, env=sub_env, cwd=workdir)
    if r.returncode != 0:
        tail = (r.stdout or r.stderr or "").strip()[:200]
        raise RuntimeError(f"claude exit {r.returncode}: {tail}")
    out_text, tin, tout, cost = "", 0, 0, 0.0
    try:
        d = json.loads(r.stdout.strip())
        if d.get("is_error"):
            raise RuntimeError(f"claude is_error: {str(d.get('result'))[:120]}")
        res = d.get("result") or ""
        if isinstance(res, list):
            res = "\n".join(b.get("text", "") for b in res if isinstance(b, dict))
        out_text = res
        u = d.get("usage") or {}
        tin = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
        tout = u.get("output_tokens", 0)
        cost = d.get("total_cost_usd") or 0.0
    except json.JSONDecodeError:
        out_text = r.stdout.strip()
    return out_text[:6000], f"claude-cli/{model}", tin, tout, round(float(cost), 6)

def call_codex(env, content, workdir):
    binpath = env.get("CODEX_BIN") or CODEX_BIN_DEFAULT
    prompt = f"{SYSTEM}\n\n被审 artifact:\n\n{content[:MAX_CHARS]}\n\n请严格按上述 JSON 格式输出评审结果。"
    r = subprocess.run(
        [binpath, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "-C", workdir, prompt],
        capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"codex exit {r.returncode}: {(r.stderr or '').strip()[:120]}")
    m = re.search(r"(?:tokens used|total tokens)\s*:?\s*([\d,]+)", r.stderr or "", re.IGNORECASE)
    tout = int(m.group(1).replace(",", "")) if m else 0
    return r.stdout.strip()[:6000], "codex(default)", len(prompt) // 4, tout, 0.0

PROVIDERS = [
    ("glm",    "ZHIPUAI_API_KEY",   call_glm),
    ("claude", "CLAUDE_RELAY_KEY",  call_claude_cli),
    ("gemini", "GEMINI_API_KEY",    call_gemini),
    ("codex",  None,                call_codex),
]

def main():
    ap = argparse.ArgumentParser(description="多模型候选评审管线")
    ap.add_argument("--env", default="providers.env", help="provider 环境文件(KEY=value)")
    ap.add_argument("--out", default="./reviews", help="评审结果输出目录")
    ap.add_argument("--workdir", default=os.getcwd(), help="CLI 子进程工作目录")
    ap.add_argument("targets", nargs="*", help="待评审文件(缺省时用 artifacts 目录标准文件)")
    args = ap.parse_args()
    env = load_env(args.env)
    os.makedirs(args.out, exist_ok=True)
    if args.targets:
        targets = [(os.path.basename(t), open(t, encoding="utf-8").read()[-8000:]) for t in args.targets]
    else:
        art = env.get("ARTIFACT_DIR") or "."
        targets = []
        for name, tail in (("lessons", "LESSONS.jsonl"), ("rules", "rules/operator-rules-v1.md"), ("growth", "GROWTH.md")):
            p = os.path.join(art, tail)
            if os.path.isfile(p):
                targets.append((name, open(p, encoding="utf-8").read()[-8000:]))
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    rows = []
    for name, keyenv, fn in PROVIDERS:
        if keyenv and not env.get(keyenv):
            print(f"⏭ {name}: 未配置 {keyenv},跳过")
            continue
        for tname, text in targets:
            try:
                out, model, tin, tout, cost = fn(env, f"被审 artifact:{tname}\n\n{text}", args.workdir) if name in ("claude", "codex") else fn(env, f"被审 artifact:{tname}\n\n{text}")
                rows.append({"ts": ts, "provider": name, "model": model, "target": tname,
                             "verdict_text": out[:6000], "usage_in": tin, "usage_out": tout, "cost_usd": cost})
                print(f"✅ {name}/{model}/{tname}: 已评审(输入 {tin} / 输出 {tout} token, 成本 ${cost})")
            except Exception as e:
                msg = str(e)[:120]
                if "exit" in msg.lower() or "claude exit" in msg.lower() or "codex exit" in msg.lower():
                    stage = "执行"
                elif "HTTP" in msg or "timed out" in msg.lower() or "Timeout" in type(e).__name__:
                    stage = "传输"
                else:
                    stage = "生成"
                print(f"❌ {name} [{stage}]: {type(e).__name__}: {msg}")
    if rows:
        path = os.path.join(args.out, f"reviews-{ts[:16].replace(':','-')}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"📁 评审结果: {path}")
        with open(os.path.join(args.out, "provider-usage.jsonl"), "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"ts": r["ts"], "provider": r["provider"], "model": r["model"],
                                    "in": r["usage_in"], "out": r["usage_out"], "cost_usd": r["cost_usd"]}) + "\n")
    else:
        print("(无可用 provider,全部跳过)")

if __name__ == "__main__":
    main()
