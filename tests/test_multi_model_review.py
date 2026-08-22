#!/usr/bin/env python3
"""stdlib-only unit tests for multi-model-review's structured output parsing.

Covers the offline-testable parsing paths: env loading, OpenAI-compatible
response normalization, Claude CLI JSON output parsing (blocks / usage /
error / non-JSON fallback), and the Codex token-usage regex. All network
and subprocess boundaries are mocked — zero dependencies, zero network.

Run:
    python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import multi_model_review as mmr  # noqa: E402


class TestLoadEnv(unittest.TestCase):

    def _write(self, content):
        import tempfile
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        self.addCleanup(os.unlink, path)
        return path

    def test_parses_key_values_and_skips_comments(self):
        path = self._write("# comment\nZHIPUAI_API_KEY=abc\nGEMINI_API_KEY=def\n\nGEMINI_MODEL=a,b\n")
        env = mmr.load_env(path)
        self.assertEqual(env["ZHIPUAI_API_KEY"], "abc")
        self.assertEqual(env["GEMINI_MODEL"], "a,b")
        self.assertNotIn("GEMINI_API_KEY" and "#" in env, [])
        self.assertNotIn("#", env)

    def test_missing_file_returns_empty(self):
        env = mmr.load_env("/nonexistent/definitely-missing.env")
        self.assertEqual(env, {})


class TestPostOpenAICompat(unittest.TestCase):

    def test_str_content(self):
        resp = {"choices": [{"message": {"content": "评审文本"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        with mock.patch.object(mmr, "http_post_json", return_value=resp) as post:
            text, usage = mmr.post_openai_compat("https://api.example.com", "k", "m", "content")
        self.assertEqual(text, "评审文本")
        self.assertEqual(usage["prompt_tokens"], 10)
        post.assert_called_once()
        # 请求体要点:模型、system+user、温度
        body = post.call_args[0][2]
        self.assertEqual(body["model"], "m")
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body["messages"][1]["content"], "content")

    def test_list_content_joined(self):
        resp = {"choices": [{"message": {"content": [{"text": "A"}, {"text": "B"}]}}], "usage": {}}
        with mock.patch.object(mmr, "http_post_json", return_value=resp):
            text, _ = mmr.post_openai_compat("https://api.example.com", "k", "m", "content")
        self.assertEqual(text, "A\nB")

    def test_missing_choices_raises(self):
        resp = {"error": "nope"}
        with mock.patch.object(mmr, "http_post_json", return_value=resp):
            with self.assertRaises(RuntimeError):
                mmr.post_openai_compat("https://api.example.com", "k", "m", "content")

    def test_gemini_uses_max_completion_tokens(self):
        resp = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
        with mock.patch.object(mmr, "http_post_json", return_value=resp) as post:
            mmr.post_openai_compat("https://api.example.com", "k", "m", "content", completion_key="max_completion_tokens")
        body = post.call_args[0][2]
        self.assertIn("max_completion_tokens", body)
        self.assertNotIn("max_tokens", body)


class TestClaudeCliParsing(unittest.TestCase):

    def _run(self, stdout, returncode=0):
        r = mock.Mock()
        r.returncode = returncode
        r.stdout = stdout
        r.stderr = ""
        return r

    def test_json_result_with_blocks_and_usage(self):
        stdout = json.dumps({
            "is_error": False,
            "result": [{"type": "text", "text": "第一部分"}, {"type": "text", "text": "第二部分"}],
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 20, "output_tokens": 50},
            "total_cost_usd": 0.1234567,
        })
        with mock.patch.object(mmr.subprocess, "run", return_value=self._run(stdout)) as run:
            text, model, tin, tout, cost = mmr.call_claude_cli({}, "被审内容", "/tmp")
        self.assertEqual(text, "第一部分\n第二部分")
        self.assertEqual(model, "claude-cli/claude-opus-4-5")
        self.assertEqual(tin, 120)
        self.assertEqual(tout, 50)
        self.assertEqual(cost, 0.123457)

    def test_is_error_raises(self):
        stdout = json.dumps({"is_error": True, "result": "boom"})
        with mock.patch.object(mmr.subprocess, "run", return_value=self._run(stdout)):
            with self.assertRaises(RuntimeError) as ctx:
                mmr.call_claude_cli({}, "内容", "/tmp")
        self.assertIn("is_error", str(ctx.exception))

    def test_nonzero_exit_raises(self):
        with mock.patch.object(mmr.subprocess, "run", return_value=self._run("", returncode=3)):
            with self.assertRaises(RuntimeError) as ctx:
                mmr.call_claude_cli({}, "内容", "/tmp")
        self.assertIn("exit 3", str(ctx.exception))

    def test_non_json_stdout_falls_back_to_raw(self):
        with mock.patch.object(mmr.subprocess, "run", return_value=self._run("plain text answer")):
            text, _, tin, tout, cost = mmr.call_claude_cli({}, "内容", "/tmp")
        self.assertEqual(text, "plain text answer")
        self.assertEqual((tin, tout, cost), (0, 0, 0.0))

    def test_relay_base_strips_v1_suffix(self):
        stdout = json.dumps({"is_error": False, "result": "ok", "usage": {}})
        with mock.patch.object(mmr.subprocess, "run", return_value=self._run(stdout)) as run:
            mmr.call_claude_cli({"CLAUDE_RELAY_BASE": "https://relay.example/v1", "CLAUDE_RELAY_KEY": "k"}, "内容", "/tmp")
        sub_env = run.call_args[1]["env"]
        self.assertEqual(sub_env["ANTHROPIC_BASE_URL"], "https://relay.example")


class TestCodexParsing(unittest.TestCase):

    def _run(self, stdout="答案", stderr="", returncode=0):
        r = mock.Mock()
        r.returncode = returncode
        r.stdout = stdout
        r.stderr = stderr
        return r

    def test_token_usage_regex(self):
        stderr = "session ended\ntotal tokens: 1,234\nend"
        with mock.patch.object(mmr.subprocess, "run", return_value=self._run("ok", stderr=stderr)):
            text, model, tin, tout, cost = mmr.call_codex({}, "内容", "/tmp")
        self.assertEqual(text, "ok")
        self.assertEqual(tout, 1234)
        self.assertEqual(model, "codex(default)")

    def test_no_token_line_counts_zero(self):
        with mock.patch.object(mmr.subprocess, "run", return_value=self._run("ok", stderr="no tokens here")):
            _, _, _, tout, _ = mmr.call_codex({}, "内容", "/tmp")
        self.assertEqual(tout, 0)

    def test_nonzero_exit_raises(self):
        with mock.patch.object(mmr.subprocess, "run", return_value=self._run(stderr="codex failed", returncode=2)):
            with self.assertRaises(RuntimeError) as ctx:
                mmr.call_codex({}, "内容", "/tmp")
        self.assertIn("exit 2", str(ctx.exception))


class TestProviderFallbacks(unittest.TestCase):

    def test_glm_401_raises_immediately(self):
        with mock.patch.object(mmr, "post_openai_compat", side_effect=RuntimeError("HTTP 401: unauthorized")):
            with self.assertRaises(RuntimeError):
                mmr.call_glm({"ZHIPUAI_API_KEY": "k"}, "内容")

    def test_glm_empty_reply_tries_next_model(self):
        # 第一个模型空回复 → 换下一个;第二个成功
        with mock.patch.object(mmr, "post_openai_compat", side_effect=[
            ("", {}),  # 空回复 → RuntimeError
            ("有效评审", {"prompt_tokens": 1, "completion_tokens": 1}),
        ]):
            text, model, tin, tout, cost = mmr.call_glm({"ZHIPUAI_API_KEY": "k", "ZHIPUAI_MODEL": "glm-5,glm-5-turbo"}, "内容")
        self.assertEqual(text, "有效评审")
        self.assertEqual(model, "glm-5-turbo")

    def test_gemini_missing_key_skips_in_main_loop(self):
        # PROVIDERS 表:gemini 需要 GEMINI_API_KEY;未配置时 main 循环跳过(表结构断言)
        names = [p[0] for p in mmr.PROVIDERS]
        self.assertEqual(names, ["glm", "claude", "gemini", "codex", "kimi", "ollama", "openrouter"])
        gemini_entry = next(p for p in mmr.PROVIDERS if p[0] == "gemini")
        self.assertEqual(gemini_entry[1], "GEMINI_API_KEY")


if __name__ == "__main__":
    unittest.main()
