"""Gemini via the `agy` CLI in print mode, on your subscription."""

import contextlib
import errno
import fcntl
import json
import os
import queue
import shutil
import signal
import subprocess
from subprocess import PIPE
import threading
import time
from pathlib import Path

from parley.protocol import Orders
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


def _kill_group(proc: subprocess.Popen) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=2)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=2)


# agy loads the user's global rules and MCP servers, and Flash obeyed them: on a full turn it
# spent 26 steps calling memweave and jcodemunch on the repo and ran out of time (2026-10-25 logs)
NO_TOOLS = ("You have no tools for this task: do not call any tool, MCP server, file read or "
            "command, and do no research. Everything you need is below. Answer at once.\n\n")


class AgySeat:
    GRACE = 15  # seconds past agy's own --print-timeout before the call is given up

    def __init__(self, model: str = "gemini-4-argon-medium", binary: str = "agy"):
        self.model = model
        self.binary = binary
        self.name = f"agy:{model}"

    def _run(self, prompt: str, timeout: float, schema: bool) -> tuple[dict, str]:
        deadline = time.monotonic() + timeout
        lines: list[str] = []
        err_chunks: list[str] = []
        try:
            with _agy_lock(deadline):
                left = max(1.0, deadline - time.monotonic())
                cmd = [self.binary, "-p", NO_TOOLS + prompt, "--output-format", "stream-json",
                       "--model", self.model, "--print-timeout", f"{max(1, int(left))}s",
                       "--sandbox", "--disable-slash-commands"]
                if schema:
                    cmd += ["--json-schema", schema_text()]
                # agy is an agent with tools and Discord text reaches its prompt: no secrets in
                # its environment, an empty working directory, and its sandbox on.
                # Headless agy finishes the answer in 26-46 s, then sometimes deadlocks in CLI
                # teardown (turns 172-178, 2026-10-25: answered in 26-46 s, then hung in teardown
                # until the 240 s timeout). Stop reading on the result line and kill its group.
                workdir = empty_workdir()
                proc = None
                out_thread = err_thread = None
                try:
                    proc = subprocess.Popen(cmd, stdout=PIPE, stderr=PIPE, text=True, errors="replace",
                                            env=safe_env(), cwd=workdir, start_new_session=True)
                    q: queue.Queue[str | None] = queue.Queue()

                    def read_out():
                        try:
                            while line := proc.stdout.readline():
                                q.put(line)
                        except ValueError:
                            pass
                        finally:
                            q.put(None)

                    def read_err():
                        try:
                            while line := proc.stderr.readline():
                                err_chunks.append(line)
                        except ValueError:
                            pass

                    out_thread = threading.Thread(target=read_out, daemon=True)
                    err_thread = threading.Thread(target=read_err, daemon=True)
                    out_thread.start()
                    err_thread.start()

                    run_deadline = time.monotonic() + left + self.GRACE
                    while True:
                        rem = run_deadline - time.monotonic()
                        if rem <= 0:
                            raise SeatError(f"agy timed out after {timeout}s")
                        try:
                            line = q.get(timeout=rem)
                        except queue.Empty as e:
                            raise SeatError(f"agy timed out after {timeout}s") from e
                        if line is None:
                            break
                        lines.append(line)
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(event, dict) and event.get("event") == "result":
                            break
                finally:
                    if proc is not None:
                        _kill_group(proc)
                        if out_thread is not None:
                            out_thread.join(timeout=1)
                        if err_thread is not None:
                            err_thread.join(timeout=1)
                        if proc.stdout is not None:
                            proc.stdout.close()
                        if proc.stderr is not None:
                            proc.stderr.close()
                    shutil.rmtree(workdir, ignore_errors=True)
        except FileNotFoundError as e:
            raise SeatError(f"agy not found: {self.binary}") from e
        except OSError as e:
            if e.errno == errno.E2BIG:
                # live: Linux MAX_ARG_STRLEN is 128 KB; prompts are 65 KB and growing
                raise SeatError(f"prompt too long for argv ({len(NO_TOOLS + prompt)} bytes, Linux max 128 KB): {e}") from e
            raise
        stdout = "".join(lines)
        stderr = "".join(err_chunks)
        final = None
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "result":
                final = event.get("result") or {}
        if final is None:
            raise SeatError(f"agy gave no result (exit {proc.returncode}): {stderr.strip()[-300:]}")
        if final.get("status") != "SUCCESS":
            raise SeatError(f"agy status {final.get('status')}")
        return final, stdout

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
