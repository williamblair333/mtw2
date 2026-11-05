# Getting Claude to act when something happens

Claude Code only acts when it's given a turn. That turn comes from you typing, or from something it
started finishing. So "notify Claude when X happens" means: give Claude something that **finishes
when X happens**.

## 1. A background watch: the main tool

Claude starts a command with `run_in_background`. When that command exits, Claude Code wakes the
session with its output. While it runs, it costs nothing: no tokens, no polling by Claude.

So write the watch as a loop that **exits only when something is wrong**, printing one line that says what:

```bash
while true; do
    sleep 60
    <check A> || { echo "A: what happened"; exit 0; }
    <check B> || { echo "B: what happened"; exit 0; }
done
```

`scripts/campaign_watch.sh` is the one for campaigns (`just watch scratch`). It exits on:

| Line   | Meaning                                                                |
| ------ | ---------------------------------------------------------------------- |
| STALL  | the bridge log has been quiet for 6 min (game hung or crashed)          |
| STUCK  | a turn has been stuck for 10+ tries (e.g. the "Victory Conditions Failed" screen) |
| DOWN   | the turn loop or the Discord bot has stopped                           |
| LOST   | England holds no towns, or has had no report for 15 min                |
| SEATS  | a ruler seat has failed for 3+ consecutive turns (any faction)         |
| AUDIT  | a new bridge bug from the turn audit (only with `WAKE_ON_AUDIT=1`)     |

Woken, Claude fixes or restarts the campaign, then starts the watch again. **A watch fires once**:
starting it again is part of handling the wake.

### Handling a wake: unstick, then fix the cause (the author, 2026-10-30)

The author's standing rule: apply fixes as they're found, whether he's at the screen or not. Every wake:

1. **Unstick the campaign first.** Read the bridge log and take a screenshot; close the popup,
   relaunch, or restart, so the game is moving again before any code changes.
2. **Fix the cause** if code could have handled it (an unknown popup, a missed scroll, a bad click):
   a branch in its own worktree, tests first, a PR on Gitea. Prefer EOP calls inside the game over
   screen clicks. One fix at a time. **Hand it to agy first** (`ask_agy`, `edits=True`,
   model `gemini-4-argon-high`, in the worktree after `uv sync`); a Claude agent only when agy
   refuses or its quota is spent (a zero-token `status ERROR`), and say so. Verify what comes back
   (tests, diff, evidence for any UI name) before merging.
3. **Merge on green tests only** (read the full pytest summary; never pipe it into the merge), then
   `just reload-bridge` during England's turn for bridge changes, or restart crash-watch for
   script changes (`just crash-watch-stop && just crash-watch`).
4. **Watch for the fix's first live run** with a one-shot background `grep -m1` on the bridge log,
   and say it's unproven until that fires.
5. **Record it:** CHANGELOG and HANDOFF. If the author is away, a one-line note to the Discord chronicle via
   the outbox: what broke, PR number, live or not yet.
6. **Start the watch again** (`WAKE_ON_AUDIT=1 just watch scratch`, so new bridge bugs from the turn audit
   wake Claude too).

Ask the author first only for what code can't reach (a screen-only problem, the GPU, Steam) or for a
change to how the rulers play: their orders are always carried out (memory: rulers-know-everything).

To get this, ask: *"start `just watch scratch` in the background and handle whatever it reports"*.

Good checks are cheap and certain: a file's age, a line in a log, a process missing, a row in a DB.
Anything that needs judgment ("is the ruler playing well?") belongs to Claude after waking, not in the loop.

### Why 2026-10-29's defeat was missed

The first watch only knew "log quiet" and "loop down". When England was conquered, the game sat on
the Victory Conditions Failed screen, and the bridge kept logging "stuck? try N" every 30 s. The log
was never quiet and the loop never stopped, so nothing fired. STUCK and LOST were added for that.
**When a watch misses something, add the check that would have caught it.**

### Why 2026-10-30's seat errors were missed

From 12:36 to 14:13, every ruler seat timed out against `heretic`: 50 seat errors in a row across
both factions, 0 orders every turn. Because the orchestrator returns empty orders when a seat fails,
turns kept advancing, the bridge log stayed active, the loop stayed up, and `WAKE_ON_AUDIT` skips
seat errors. SEATS was added for that.

### QA runs

`just qa <suite>` parks the real turn loop, Discord bot, and crash-watch while the bench runs, so a
background campaign watch would fire `DOWN`. Stop the campaign watch before running `just qa`, and
restart it after `just qa` (or `just qa-restore`) finishes.

## 2. Processes that fix things themselves (no Claude)

When the fix is mechanical, skip Claude. `just crash-watch` relaunches the game after a crash and
continues the newest save. It doesn't wake Claude. If it can't recover, the campaign watch fires
STALL or DOWN.

Before each relaunch it writes a crash report to `runs/crashes/<time>/` (log tails, a screenshot
of the crash dialog, the save it reloads, and `report.md` with the last 10 s merged); `just crashes`
lists them. On a wake after a crash, read the newest report first, fill in its Guess, and turn it
into a bench case (its Repro case slot).

crash-watch runs as the systemd user unit `parley-crash-watch` (`scripts/crash_watch_unit.sh`), not
as a child of whoever started it. On 2026-10-30 at 20:20 a crash-watch started from inside a Claude Code
background job (a QA restore) died when that job was stopped, and the next crash went unnoticed
until the campaign watch saw a 6-minute stall. Under the unit:

- `just crash-watch` starts it, or says it's already running; there's never a second one. It also
  stops a watch started the old way (`bash scripts/crash_watch.sh` with no unit).
- `just crash-watch-stop` stops it (and any old-style watch).
- `systemctl --user status parley-crash-watch` shows whether it's up. Output still goes to
  `logs/crash-watch.log`.
- Stopping the unit kills everything it started except Steam: a relaunch under the unit starts
  Steam in a scope of its own (`PARLEY_STEAM_SCOPE=1`), so the game survives a stop.
- It needs the user's systemd manager; linger is on for author, so it survives logout. The script
  sets `XDG_RUNTIME_DIR` when a non-login shell lacks it.

Starting it from a background job is safe now. Restart it after changing `crash_watch.sh` or
`relaunch_game.sh`: `just crash-watch-stop && just crash-watch`.

## 3. Alerts to you, not Claude

The turn audit posts new problems to Discord `#<game>-audit` (for example `#scratch-audit`). That's
for you to read; Claude doesn't see Discord unless it looks. Telegram from Claude is blocked by
the credential guard.

## 4. A fixed schedule: /loop

`/loop 10m <prompt>` runs a prompt every 10 minutes. `/loop <prompt>` with no interval lets Claude
pick the pace (ScheduleWakeup). Each tick costs a Claude turn even when nothing happened, so prefer
a watch (section 1) and keep /loop for things with no exit condition ("summarise every hour").

## 5. Another session

`SendMessage` reaches another running Claude session on this machine (for example Uncle J's
Refinery session, for the GPU). It wakes that session, not this one.

## 6. Long sessions and compaction

A long session gets compacted: earlier turns are replaced by a summary, so detail is lost. You asked
for a fresh session instead. Here is what works:

- **Claude can't end its own session and open a new one.** The terminal session belongs to you; only
  you (or a program you run) can start `claude`.
- **The handover file is what carries across.** HANDOFF.md, plus the memory files, hold where things
  stand. Kept current, a new session reads them and carries on.
- **To get a fresh session:** type `/clear`, then *"read HANDOFF.md and continue"*. Or quit and run
  `claude "read HANDOFF.md and continue"`. A running background watch dies with the session, so
  the new session starts it again; HANDOFF says to.
- **Unattended:** a background watch can't start an interactive session. `claude -p "<prompt>"` runs
  a headless one-shot that you can't watch or talk to. That's fine for a script, wrong for live play.
- **After a compaction, the hand-over is put back automatically** (you approved this on 2026-10-30).

### The compaction hook

`.claude/settings.json` (in the repo) has a `SessionStart` hook with matcher `compact`. Claude Code
runs it right after a compaction, and whatever it prints is added to the summarised session. It
runs `scripts/compact_context.sh`, which prints:

1. a reminder to check that `just watch scratch` is still running (a compaction doesn't kill a
   background watch, but if the watch fired just before, it has to be started again);
2. HANDOFF.md's top section, from its first `## ` heading up to the second.

It doesn't run on a new session, `/clear` or resume (matcher `compact` only). A new session reads
HANDOFF.md itself; the project CLAUDE.md and memory already point there.

**Pros**
- The session carries on with the current plan and "Next" list in front of it, not just the
  summary's version, which drops detail (state, paths, the author's rulings).
- No tokens until a compaction happens; it's ~35 lines when it does.
- Read-only. It prints and exits; it can't change the game, the repo or settings.

**Cons and limits**
- It's only as good as HANDOFF.md. A stale top section gets injected just the same, so keep the
  top section current (the session-end checklist does).
- It shows only the top section. Older sections stay on disk; Claude reads them when it needs to.
- A long top section costs context on every compaction. Keep it short.
- It's a project setting, so it applies to anyone who opens this repo in Claude Code once it's
  public. It's harmless there (it prints a doc), but they'll see our hand-over text.
- If the script fails (HANDOFF.md missing, say), Claude Code shows a hook error and the session
  goes on without it. Nothing blocks.

**Turn it off:** `/hooks` in Claude Code, or delete the `SessionStart` entry from
`.claude/settings.json`. **Test it by hand:** `echo '{}' | bash scripts/compact_context.sh`.

## Limits

- Claude only acts when woken. If the session is closed, background watches die with it; nothing
  wakes. Leave the terminal open overnight.
- A watch that fires while Claude is mid-turn is handled after that turn.
- Every wake costs a turn. Keep false alarms rare (the 15-min LOST? check can fire on a very slow
  round; that's cheap, a missed defeat isn't).
