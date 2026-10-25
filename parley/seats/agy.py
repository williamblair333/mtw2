"""Gemini via the `agy` CLI in print mode, on your subscription."""

import contextlib
import fcntl
import json
import os
import subprocess
import time
from pathlib import Path

from parley.protocol import Orders
import shutil

from parley.seats.base import SeatError, empty_workdir, safe_env, schema_text, to_orders

# Gemini calls on this machine share a few slots (lock files), across processes. On
# 2026-10-23 three concurrent calls hung and came back empty, so they ran one at a time; on
# 2026-10-24, with every call in its own empty working directory, six concurrent calls all
# answered (46 s wall, ~30 s each). One at a time starved ten rulers of a 120 s budget.
LOCK_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "parley-agy.lock"
SLOTS = int(os.environ.get("PARLEY_AGY_SLOTS", "4"))


@contextlib.contextmanager
def _agy_lock(deadline: float):
    """Wait for a free slot until the deadline; the seat's time budget includes the wait."""
    files = [open(LOCK_PATH.with_name(f"{LOCK_PATH.stem}.{k}{LOCK_PATH.suffix}"), "a") for k in range(SLOTS)]
    try:
        held = None
        while held is None:
            for f in files:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = f
                    break
                except BlockingIOError:
                    continue
            if held is None:
                if time.monotonic() >= deadline:
                    raise SeatError(f"agy busy: all {SLOTS} Gemini slots were taken for the whole turn budget")
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)
    finally:
        for f in files:
            f.close()


class AgySeat:
    def __init__(self, model: str = "gemini-4-argon-medium", binary: str = "agy"):
        self.model = model
        self.binary = binary
        self.name = f"agy:{model}"

    def _run(self, prompt: str, timeout: float, schema: bool) -> tuple[dict, str]:
        deadline = time.monotonic() + timeout
        try:
            with _agy_lock(deadline):
                left = max(1.0, deadline - time.monotonic())
                cmd = [self.binary, "-p", prompt, "--output-format", "stream-json",
                       "--model", self.model, "--print-timeout", f"{max(1, int(left))}s",
                       "--sandbox", "--disable-slash-commands"]
                if schema:
                    cmd += ["--json-schema", schema_text()]
                # agy is an agent with tools and Discord text reaches its prompt: no secrets in
                # its environment, an empty working directory, and its sandbox on.
                workdir = empty_workdir()
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=left + 15,
                                          env=safe_env(), cwd=workdir)
                finally:
                    shutil.rmtree(workdir, ignore_errors=True)
        except subprocess.TimeoutExpired as e:
            raise SeatError(f"agy timed out after {timeout}s") from e
        except FileNotFoundError as e:
            raise SeatError(f"agy not found: {self.binary}") from e
        final = None
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "result":
                final = event.get("result") or {}
        if final is None:
            raise SeatError(f"agy gave no result (exit {proc.returncode}): {proc.stderr.strip()[-300:]}")
        if final.get("status") != "SUCCESS":
            raise SeatError(f"agy status {final.get('status')}")
        return final, proc.stdout

    def decide(self, prompt: str, *, game_id: str, turn: int, faction: str,
               timeout: float) -> tuple[Orders, str]:
        final, raw = self._run(prompt, timeout, schema=True)
        payload = final.get("structured_output", final.get("response", ""))
        if not payload or (isinstance(payload, str) and not payload.strip()):
            # agy reports SUCCESS with an empty answer when it hits --print-timeout, and also
            # when the model fails to produce the structured answer (seen with flash-medium).
            raise SeatError(f"agy returned an empty answer (timeout of {timeout}s, or the model "
                            "failed the JSON schema)")
        return to_orders(payload, game_id=game_id, turn=turn, faction=faction), raw

    def chat(self, prompt: str, *, timeout: float) -> str:
        final, _ = self._run(prompt, timeout, schema=False)
        return str(final.get("response") or "").strip()
