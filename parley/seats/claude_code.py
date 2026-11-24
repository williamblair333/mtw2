"""Claude via the `claude` CLI in print mode, on your subscription. No tools, no MCP."""

import json
import re
import shutil
import subprocess

from parley.protocol import Orders
from parley.seats.base import SeatError, SeatLimit, empty_workdir, safe_env, schema_text, to_orders

# the CLI's words when the subscription is used up ("Claude AI usage limit reached",
# "You've hit your limit", "You've hit your session limit", "5-hour limit reached", and live 11-20
# "You've hit your 5-hour limit · resets 1pm (...) · out of usage credits", which matched none of these:
# the seats failed as plain errors and ~66 turns (2143-2209) passed with no ruler, never paused);
# anything else stays a plain SeatError
LIMIT = re.compile(
    r"usage limit|hit your (?:session |weekly |\d+-hour )?limit|limit reached|rate.?limit|quota"
    r"|out of usage credits",
    re.I,
)


class ClaudeCodeSeat:
    def __init__(self, model: str = "sonnet", binary: str = "claude"):
        self.model = model
        self.binary = binary
        self.name = f"claude:{model}"

    def _run(self, prompt: str, timeout: float, schema: bool) -> tuple[dict, str]:
        # the prompt goes on stdin: live 11-15 turn 1038 France's passed 128 KB, one argv string's
        # limit on Linux (MAX_ARG_STRLEN), and "Argument list too long" stopped the turn loop
        cmd = [self.binary, "-p", "--output-format", "json", "--model", self.model,
               "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
        if schema:
            cmd += ["--json-schema", schema_text()]
        workdir = empty_workdir()  # no repo, no env file; and no secrets in the environment
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, errors="replace",
                                  timeout=timeout, env=safe_env(), cwd=workdir)
        except subprocess.TimeoutExpired as e:
            raise SeatError(f"claude timed out after {timeout}s") from e
        except FileNotFoundError as e:
            raise SeatError(f"claude not found: {self.binary}") from e
        except OSError as e:  # any other launch failure fails the seat, not the loop
            raise SeatError(f"claude couldn't start: {e}") from e
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise SeatError(f"claude exit {proc.returncode}: {proc.stderr.strip()[-300:]}") from e
        if not isinstance(result, dict) or result.get("is_error"):
            text = str(result.get("result") or result) if isinstance(result, dict) else str(result)
            if LIMIT.search(text):
                raise SeatLimit(f"claude usage limit: {text[:200]}")
            raise SeatError(f"claude failed: {text[:300]}")
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
