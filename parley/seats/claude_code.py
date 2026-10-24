"""Claude via the `claude` CLI in print mode, on your subscription. No tools, no MCP."""

import json
import subprocess

from parley.protocol import Orders
import shutil

from parley.seats.base import SeatError, empty_workdir, safe_env, schema_text, to_orders


class ClaudeCodeSeat:
    def __init__(self, model: str = "sonnet", binary: str = "claude"):
        self.model = model
        self.binary = binary
        self.name = f"claude:{model}"

    def _run(self, prompt: str, timeout: float, schema: bool) -> tuple[dict, str]:
        cmd = [self.binary, "-p", prompt, "--output-format", "json", "--model", self.model,
               "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
        if schema:
            cmd += ["--json-schema", schema_text()]
        workdir = empty_workdir()  # no repo, no env file; and no secrets in the environment
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                  env=safe_env(), cwd=workdir)
        except subprocess.TimeoutExpired as e:
            raise SeatError(f"claude timed out after {timeout}s") from e
        except FileNotFoundError as e:
            raise SeatError(f"claude not found: {self.binary}") from e
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise SeatError(f"claude exit {proc.returncode}: {proc.stderr.strip()[-300:]}") from e
        if not isinstance(result, dict) or result.get("is_error"):
            raise SeatError(f"claude failed: {str(result)[:300]}")
        return result, proc.stdout

    def decide(self, prompt: str, *, game_id: str, turn: int, faction: str,
               timeout: float) -> tuple[Orders, str]:
        result, raw = self._run(prompt, timeout, schema=True)
        if "structured_output" not in result:
            raise SeatError(f"claude gave no structured output: {str(result.get('result'))[:300]}")
        return to_orders(result["structured_output"], game_id=game_id, turn=turn,
                         faction=faction), raw

    def chat(self, prompt: str, *, timeout: float) -> str:
        result, _ = self._run(prompt, timeout, schema=False)
        return str(result.get("result") or "").strip()
