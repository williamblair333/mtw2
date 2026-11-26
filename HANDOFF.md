# Handoff

## 2026-11-26 (06:00): campaign stopped; tc desktop focus theft; waiting on the community

**tc: campaign `scratch` stopped on William's word at turn ~5380** ("I thought we were good for now").
Turn loop, crash-watch and resume-at-boot are off; `paused.txt` is in place; the game window is still
open. `just play scratch` (plus `just crash-watch`, `just resume-at-boot scratch`) starts it again.
Don't restart the campaign or its watch until William asks for more live testing.

- **Crash 05:33, turn 5379** (`runs/crashes/2026-11-26-053336`): eip in the heap (1d1fea74), the saved
  stack holds pixel values, no game frames. Suspected cause: KDE restored William's session at the 03:00
  boot, and a Claude Code session started at 04:20 in its Konsole took focus from the game 13 times;
  each crash-watch focus grab made the game reload its campaign map (5 reloads in 6 min before the
  crash). One crash, so an inference. The crash-watch relaunch then failed (main menu, no save load in
  240 s); `just relaunch-game` by hand worked at 05:41. Fix applied: KDE on tc now starts with an
  empty session (`~/.config/ksmserverrc` loginMode=emptySession, Plasma 5). Memory `tc-focus-theft`.
- **Limit-pause #666 proven live 11-25:** the Claude quota ran out at 14:11; the campaign paused and
  resumed by itself at 16:45.
- **Upstream:** Fynn [AGO] answered the call to arms in Discord (press any button by name via
  `getUiElement`/`execute`; most #89 asks possible; diplomatic proposals hardest). EOP #91 is solved
  on our side but still open: William posts the drafted comment and closes it. Until then the
  `upstream-current` gate refuses public publishes; then set #91's state in `docs/upstream.toml` and
  push the pending public refresh (#734, #736).
- **Not yet proven live:** #728 (needs a papal election during an offer) and #734's hold (needs a
  ruler's order; log line "game AI recruiting off (the ruler's order): held").
- **Next:** check GitHub Discussions #4, issues and stars; ruler play quality when testing resumes.

## 2026-11-25 (09:00): clean install proven; docs plain and public; call to arms ready

**Running on tc:** campaign `scratch` from turn 4826 on `main` (1507a71), bridge 158f76ad6d20, rulers
claude:haiku; turn loop, crash-watch and `WATCH_BOT=0 just watch scratch` up since 08:51. The turn-5045
save was lost: 12 crash replays overwrote all 6 autosaves (memory `replay-trials-eat-autosaves`). The
rulers' notes still hold the lost turns 4827-5045; the loop archives each old answer as it reaches it.

- **Clean install (#5) done:** fresh Debian 13 VM (parley-fresh on the main machine, 4 vCPU / 6 GB): `just
  install-eop` from the public `parley-fork6` release wrote EOP's config (#722 proven), main menu with
  EOP, new campaign, the loop reloaded a stale bridge on its own, and France (`ollama:qwen3.5:9b`, host
  GPU via tunnel) answered: 1 move, 1 refused assassination (a priest). The VM is shut off.
- **#723:** a preflight gate refuses a local `virsh start`/`virt-install` with < 14 GiB available (11-24
  a test VM hung the main machine). It passed this morning's start at 26 GiB.
- **Turn-4826 crash:** 0 crashes in 12 replays from its save (plus the 11-24 relaunch: 13 passes). In
  `medieval2.exe`: a loop at 0x719320 calls 0x749fd0 on each item of a list; one item was bad and the
  call jumped to 12135e12. Same routine as turn 124's crash (11-11, eip 007193cf). It fired 0.4 s into
  the rebels' turn, 3 h after launch. Not reproducible from the save, so likely state built up in the
  long-running process. Watch for a repeat; crash-watch recovers it.
- **Docs (#724, #725):** plain wording for players; stale claims fixed (no screen clicks since 11-22,
  2,123 tests). Public GitHub refreshed to 03a61a6 (scrub problems=0); Gitea mtw2-public mirrors it.
- **Call to arms:** `review/CALL-TO-ARMS-DISCORD.md` (1,721 chars, one Discord message, links wrapped
  in `< >`); suggested channel EOP Discord `#lua-scripting`. William posts it.
- **tc disk:** deleted the t1447 archive (26 GB) and `scratch.run1-9` (16 GB); 33 GB free.
- **Ollama container** lost the GPU twice (NVML error after a systemd daemon-reload); Uncle J restarts it
  and plans the CDI fix with a Docker restart.
- **#728 (10:00, live on tc, bridge e86bbe7f0e2d):** crash at turn 4877 (09:49:44, report
  `runs/crashes/2026-11-25-095032`): England's adoption "accept" pressed a `DECIDED_VOTE_BUTTON` on the
  papal results scroll (it shows as "unnamed", so the by-name skip missed it; `choice_buttons` finds a
  check and X by shape). Same site as the 11-20 08:36 crash (`medieval2.exe+0x7f47bc`), which closes
  that open item too. Three class guards (open_choices, choice_buttons, press_choice). Live proof waits
  on the next papal election during an offer.
- **#727:** mtw2's VM memory gate retired; the Refinery's ram-gate hook covers every session.
- **#730, France's prompt under 60 KB (live 10:30, turn 4937: 59,941 bytes, was 68.6 KB this
  morning; France answered 20 orders, 0 refused):** garrisons whose short line repeated their town's
  fold into one line naming them; "str N" (defined at the top of each section) replaces "(strength
  rating N, not men)", 113 times. Lossless. Headroom is thin: France's size moves with its town count.
- **France's money (found 10:35):** income -3,496 to -4,693 a turn, army upkeep 174,183 (84% of costs).
  France's own game AI trained 175 units in French towns 09:51-10:34 while its ruler disbanded to pay
  upkeep. **#732 (live 10:44):** the bridge counts EOP's `onUnitTrained` for seated factions (a ruler's
  recruits bypass the game's queue, so all are the AI's) and the prompt says what was trained and the
  upkeep it adds ("Your game AI trained 4 units ... they add 700 upkeep a turn: ..."). 15 min live with
  the new event, no crash.
- **#734 (live 11:20): order `game_ai_recruiting` on/off.** No fork change: with it off the bridge holds
  the realm's recruitment pools at 0 from the AI's unfreeze to the faction's next turn start
  (`pool_hold.json` beside `training.json`), then gives them back with their regrowth before the
  ruler's orders. The recruit help no longer says "Nobody recruits for you" (false for an AI-run realm).
  France hasn't used it yet; its AI trained 0-1 units a report since 11:20 (treasury low). Live proof
  of the hold waits on a ruler's order: look for "game AI recruiting off (the ruler's order): held".
- **Next:** ruler play quality.

## 2026-11-24 (07:50): 100-turn run passed; recruit pool counts

- **Clean run:** turns 4641-4857 (217 turns), both seats every turn, 0 orders refused at turn start
  by the validator's misses until 4863. It survived the 23:59 power-off (crash-watch relaunched at 03:02)
  and one real game crash at turn 4826 (06:06, access violation at 12135e12, no module: new site;
  report runs/crashes/2026-11-24-060628 on tc). Not yet diagnosed.
- **#719:** England queued six Town Militia at Dijon (turn 4863), its pool held two, the game refused
  four; the watch's applied-share alarm stopped it. The bridge now sends each pool's count, the report
  shows `Unit ×N` when N < 9 (the queue limit), and the validator sums a turn's recruits against it.
  Live from turn 4873: England's report shows e.g. `Heavy the author Militia ×6`.
- **Lesson:** the session sat idle from 23:59 to 07:10; arm a wait for the 03:00 boot when the watch dies.
- **Next:** the turn-4826 crash; France's prompt to 60 KB; clean-install test.

## 2026-11-23 (21:10): orders carried out, the bridge can't run old Lua, public refresh, Discussions

**Running on tc:** campaign `scratch`, turn 4698 at 23:00 on `main` (#716). The watch runs from this machine.
**Clean run so far (checked 23:01):** turns 4641-4698, 58 turns, both seats answered every turn, 1,010 orders,
0 refused by the validator, no ERROR or traceback in the loop log, no hand fix. tc powers off at 23:59, so the
100th clean turn (4740) falls after the 03:00 power-on; the count holds only if the loop comes back on its own.

- **Order audit, turns 4330-4633:** the game ran 3,910 orders, about 120 failed. #713/#716: a fleet sent
  onto land sails to the nearest sea within 12 tiles; an army or agent aimed at sea goes to land
  within 3; an agent sent into a foreign town stops beside it. The validator now sums a turn's hires
  against 20 units, treats a garrison and its general as one army, and refuses moves into a full own
  town. Orders it refuses get **one same-turn correction ask** (`answer_refused.txt`,
  `rejected_first.json`); an empty correction keeps what passed. Left: stale names (an agent died or an
  army merged since the report), and far fleet guesses with no sea within 12 (not measured).
  Bench on the real game: navy (instant) and envoys all pass (runs/qa/2026-11-23-2058-navy.md, -2105-envoys.md).
- **Lookups fixes:** #711 town keys match whatever their case (live turn 4632: `town:corinth` etc. came
  back in full); #712 the short garrison keeps its `merge_units would combine` line.
- **No old Lua (#715):** `parley/bridge_build.py` compares this checkout's bridge with the installed and
  loaded stamps; any difference installs and reloads. The bench checks before it parks the real run; the
  turn loop checks at start and once a minute. Proven live: a git-only deploy of #716 was installed and
  reloaded by the loop in 2 s. (The stamp files are CRLF under Wine: compare stripped.)
- **Public:** GitHub williamblair333/mtw2 and Gitea mtw2-public both at 4da37d8 (scrub problems=0;
  William approved 11-23). Replies go to GitHub Discussions, "Start here" #4.
- **Next:** the 100-turn clean run (count from #716's deploy, turn ~4640); France's prompt (~71 KB) to
  60 KB (primer, output rules, field-army troops); a clean-install test on a fresh machine.

## 2026-11-23 (15:25): France's prompt 135 → 80 KB with lookups; `just seat-set`; outreach draft rewritten

**Running on tc:** campaign `scratch`, turn ~4476 on `main` (#709). France has `lookups = true`
(set by hand 11-23; use `just seat-set` from now on). The watch still runs from this machine.

- **#706:** town lines print the game name and region only when they differ from the id; no empty
  queue/build lines; garrisons drop "in X"; "moves" stays on the army's line. Live turn 4454: 0 refused.
- **#707 lookups** (William's option 2; spec `docs/superpowers/specs/2026-11-23-ruler-lookups-design.md`):
  a seat with `lookups` gets short town entries and may answer `{"lookup": ["town:<id>"|"town:all"|"family"]}`
  first; it gets the details and one more ask (`lookup.txt`, `answer1.txt` in the turn folder).
  **#709:** family behind the `family` lookup; agents of one kind on one spot share a line (all seats).
  Live turn 4475: France 80.2 KB (was ~135), England 60.2 KB, 0 refused each. France hasn't used a
  lookup yet (it only disbands and sets taxes: 514 florins). **Judge after ~30 turns** against the
  baseline (turns 4425-58: 135 KB average, 0 refused, 153 disbands, 38 set_tax, no recruits).
- **#708 `just seat-set <game> <faction> <key> <value>`:** a fresh timestamped backup each run, refuses
  unknown keys and bad TOML, keeps the old file if the new one won't load. STANDARDS `live-config-change`.
  (A hand cp on 11-23 broke on a line wrap and its rerun overwrote the backup.)
- **Outreach draft** `review/TOTAL-WAR-COMMUNITY-OUTREACH.md` rewritten against facts (old one kept as
  `.2026-10-28.md`). Checked: EOP PR #90 and issue #89 are still open (EOP-Labs/M2TWEOP-library); the
  REX/M2EX Discord invite is dead; the EOP and Modding Den invites work; the public GitHub copy was
  last pushed 11-05. Left as TODOs: 100-turn clean run, clean-install test, public refresh, a reply venue.
- **Next:** the 100-turn clean run counts from turn ~4476. Prompt cuts left: primer 7.4 KB and output
  rules 6.2 KB (every seat), field-army troops behind `army:<id>`.

## 2026-11-23 (12:40): two prompt cuts and the dead-click cleanup are live; Gemini is out of quota until 11-28

**Running on tc:** campaign `scratch`, turn ~4390 on `main` (#704), loop restarted ~12:35. The watch
runs from this machine over ssh (`WATCH_BOT=0 just watch scratch` on tc).

- **Live proofs:** #699's coast snap fired (turn 4335, England: "(91,163) is sea; moving to the nearest
  land (90,162)"). The papal close gadget hasn't fired on its own yet: no results scroll has got stuck
  since 11-22, and the only log line is the 03:48 hand close.
- **Prompt (France ~138 KB at turn 4377):** YOUR SETTLEMENTS + YOUR ARMIES 86 KB (town lines 26.5, recruit
  lists 14, troops 12.5), family 12.3, primer 7.4, agents 6.9, output rules 6.0. #702: armies with the
  same mercenary offers print them once (live turn 4387: 25 "same as", 6 full). #704: dead relatives
  on one line; a spouse's faction is printed only when it's foreign (live turn 4388: one "- dead:" line, no
  "(france)" tags, prompt 136.6 KB; no refused hires in turns 4387-89). **Next cuts:** town header lines
  (public order breakdown ~100 B x 59), recruit lists, the primer and output rules. Keep them lossless
  (rulers-know-everything). The 60 KB target needs a format change for towns, not more trims.
- **#703:** deleted `after-relaunch`/`resume_real_after_relaunch`, `find_minimized`/`minimized_slots`,
  `BUTTONS`, `NOCLICK_TURNS` (nothing called them). crash-watch's `refocus_game.sh` / `wmctrl -c` are
  still William's call.
- **agy:** the AI Pro weekly quota ran out 11-23 ~12:25 (429, "resets in 123h": ~11-28 16:00). `ask_agy`
  also still fails auth in a fresh session. Until then do the work yourself or use `ask_heretic`.

## 2026-11-23 (11:25): three watch wakes fixed; agy's delegate tool can't see the new login

**Running on tc:** campaign `scratch`, turn ~4345 on `main` (#700), bridge reloaded 11:20. Rulers
claude:haiku. Start `just watch scratch` in the background first thing (tc is off 23:59-03:00).

- **Done today:** trend alarm on varied mistakes (#698), map bounds + sea-to-coast moves (#699, map
  line live in turn-4322 prompts; no coast snap seen live yet), report missing after a bench restore
  (#700). Yesterday: papal scroll by close gadget (#693), stale-bridge refusal (#694), prompt cuts
  (#692, #696; France's prompt ~144 KB live).
- **agy:** William signed in 11-23 ~10:45. `agy -p` from a shell works; the delegate MCP's `ask_agy`
  still fails "not logged in" (its process predates the login). Restart the Claude session; until
  then run `agy -p "$(cat brief)" --model gemini-4-argon-high --mode accept-edits` in a worktree.
  argon-high spent 30 min exploring the restore bug and changed nothing: give it the function name.
- **Watch for:** a "moving to the nearest land" note in results.json (#699 live proof); a papal close
  log line ("closed papal_election_results_scroll by its close gadget").
- **Outreach (call to arms), in order:** 100-turn clean unattended run on record; prompt under 60 KB
  (armies, family, diplomacy next); rewrite `review/TOTAL-WAR-COMMUNITY-OUTREACH.md` against facts;
  refresh the public GitHub copy (last 2026-11-05) with `_review/scrub_public.py`; clean-install test;
  William posts.
- **Leftover:** worktree `../mtw2-wt-restore-report` holds the untracked `restore-0800-bridge.log`
  (don't commit). Dead click helpers still to clean up (see 11-22 entry).

## 2026-11-22 (03:55): click fallbacks deleted; one escape path still open

**Running on tc:** campaign `scratch`, turn ~3200+ on `main` (#690), fork level 6. **The watch is NOT
running:** start `just watch scratch` in the background first thing.

- **First thing next: the papal results scroll (OPEN, it stalls turns).** `try_dismiss` still writes an
  "escape" request for a `papal_election_results_scroll` that stays open, and since #689 the turn loop
  refuses it. Live 03:17–03:48 France's turn sat stuck, and `just click-coverage` is INCOMPLETE on the
  unmapped `escape` kind (48x). Closed by hand: part 0 of the scroll is `SCROLL_CLOSE_GADGET` (readBytes
  `ec5d3601`), and `activate()` on it closed the scroll (03:48:39; England's turn at 03:49:45). To do:
  1. Replace the escape request with that class-checked `activate()`.
  2. Add a forced bench case.
  3. Map the kind in `games/click-coverage.toml`.

  Memory: `papal-results-close-gadget`.
- **Done 11-21:** every other census click kind passes a `--kind noclick` bench case, the stuck-turn
  reopen included (#686, #689). The screen-input code is deleted (#689, reviewed by Gemini).
- **Watch wakes fixed:** walking merges (#687), shared mercenary pools (#688), the no-bot host (#690).
- **Left for a cleanup:** dead helpers only the deleted paths used: `parley.qa after-relaunch`,
  `find_minimized`/`minimized_slots`, `BUTTONS`, `NOCLICK_TURNS`. crash-watch's `refocus_game.sh`
  (`windowactivate`) and its `wmctrl -c` error-box close bypass the guard; the author's call.
- **The author's call (still):** a separate account or API key for the rulers. They share this session's
  5-hour quota.

## 2026-11-20 (13:30): rulers ran dry on the shared Claude quota; the limit now pauses the game

**Running on tc:** campaign `scratch` at turn ~2215 on `main` (#666), fork build `d37eb120` (forkLevel 6).

- **No screen clicks since 08:15.** Every click type in the logs has a no-click path. The last one, the
  papal notice's "accept", is pressed by element (bench, every click refused, 08:26:59). Next: run
  `just click-census` after a day of play, then delete the unused click fallbacks.
- **About 66 turns (2143–2209, 11:30–13:00) ran with no ruler.** Both seats' `claude` calls hit the
  account's 5-hour limit. This session uses the same account, and its heavy use drained the quota.
  The existing pause-on-`SeatLimit` never ran because `LIMIT` didn't match "You've hit your 5-hour limit
  · … · out of usage credits". Fixed in #666, with a test on the live text. **The author's call:** a separate
  account or API key for the rulers, so a long session can't starve them.
- **Watch noise cut:** #663 compares answer time per order (big turns aren't slow); #665 makes a faction
  with 20+ towns alert only on a 5% loss. Wakes on war losses (Antwerp to France, Captain Tostig's army
  destroyed between report and orders) were all correct play, with correct refusals.
- **`just ui-classes`** (#664) names UI classes from the exe's RTTI. Its cross-check test fixed a mistyped
  vtable in `K.UI_CLASSES` (UNDECIDED_VOTE_BUTTON is `dc493901`).
- **agy this session:** 5 of 11 jobs were usable as delivered. The rest timed out, stalled, or needed
  review fixes: an unpaced reopen loop, `execute()` on non-buttons, an edited live-log fixture, a dropped
  alert floor, and an over-built limit rewrite that wasn't taken. The `ask_agy` 1800 s idle fix
  (Refinery #369) needs a session restart.

## 2026-11-20 (08:35): papal vote, notices and offer icons by element; only fallbacks click now

**Running on tc:** campaign `scratch` at turn ~2018 on `main`, fork build `d37eb120` (forkLevel 6).

- **Papal vote, no click (W11/W22):** #659 presses the ruler's candidate on `papal_election_scroll` by
  element, choosing only parts whose class is `UI::VOTE_BUTTON` (vtable `9c3e3901` via `readBytes`, class
  names from the exe's RTTI). Proven on the bench with every click refused: `just qa popups --case
  papal_election_vote --kind noclick` passed at 08:28 ("pressed papal_vote_button on papal_election_scroll
  by its element", then the results window). `needs_click` is removed from that case.
- **Offer icons (#658):** a held marriage/adoption offer whose scroll isn't bound opens the next minimized
  icon by element, every 5 s. Not seen live yet.
- **Crash-watch refocus (#657):** live, but not yet triggered by a real loss of focus.
- **Watch on tc (#656):** `just watch scratch` works with no flag. Its first wake was a TREND (England's
  median answer time 62 s vs 41 s), most likely today's bench runs and loop restarts. Recheck after an
  hour of plain play.
- **Bench over ssh:** run `just qa <suite> --case X --kind noclick` (the recipe borrows the desktop's
  DISPLAY). A bare `python -m parley.qa` over ssh has no display and fails on "game window not found".
- **agy:** long jobs died at the MCP 1800 s idle limit. Refinery #369 fixes it after a session restart.
- **Crash 08:36 after the papal bench (open):** the real campaign crashed 6 min after `qa-restore`, at
  `medieval2.exe+0x7f47bc` in `UI::DECIDED_VOTE_BUTTON` slot 0. It was called from
  `PAPAL_ELECTION_RESULTS_SCROLL` and `UI_REQUEST`, with `UI_MESSAGE_ICON` below. The real campaign had
  no papal message after the restore. Likely: the bench election's results message stayed in the icon
  stack across the in-process `loadGame`; the bridge opened it at 08:33–08:34, and the game later tore
  down a results scroll whose vote buttons were gone. Report and logs: `runs/crashes/2026-11-20-083612`
  on tc, a copy in `_review/crash-1120-0836/`. **Fix next:** after a bench case, the restore relaunches the
  game (or clears the message stack) before the real save plays on. The bench case for it: papal vote,
  then restore, then open every icon, and the game is still alive 60 s later. The stack was symbolized
  with the exe's RTTI (scratch `pe.py`; worth moving into `scripts/` as a tool).
- **Next:** run `just click-census` after a day of play. Delete each click fallback that has gone unused.
  The "accept by reading a scroll" click (1 seen) is the last one with no element path.

## 2026-11-20 (07:35): minimized icons open with no click (W52 done live)

**Running on tc:** campaign `scratch` at turn ~1991 on `main` (#654), with fork build `d37eb120`
(forkLevel 6; zip sha256 fd7d7e11…). The turn loop, crash-watch and `WATCH_BOT=0 just watch scratch` are up.

- **Fix:** EOP's `execute()` calls `useButtonFunc`, which only works on buttons. Every UI element has a
  virtual "use" function at vtable slot 60: `useButtonFunc` for `UI_BUTTON`, and "open the message" for
  `UI::UI_MESSAGE_ICON` (`0xb302d0`). Fork level 6 adds `uiElementStruct:activate()`, which calls slot 60.
  Bridge #654 opens the bottom 47x47 root icon with it on a stuck turn. The click stays as the fallback.
- **Proven live:** 07:33:16 "reopened minimized message 1 of 2 by its element", followed at once by
  `onIncomingMessage` event 40, handled by `clear_messages`. Try 2 opened icon 2 of 2, the turn went
  1990 → 1991, and no `kind=minimized` click was made.
- **Found on the way:** the game froze for 8 min (07:13–07:21) while a Steam window had focus; MTW2 stops
  when it isn't the active window. Nothing caught it. agy is adding a refocus check to crash-watch
  (worktree `../mtw2-wt-focus`). The cause of the focus change isn't known.
- **Watch on tc:** run `WATCH_BOT=0 just watch scratch`. tc has no Discord token, so a plain watch exits
  "DOWN: bot not running" at once.
- **Next:** papal vote and notices by element (agy, worktree `../mtw2-wt-papal`). Then the offer icons
  (`open kind=marriage/adoption`) through the same `activate()`. Then delete the minimized click path once
  the click census shows it unused for a day.

## 2026-11-20 (06:30): `execute()` can't press a message icon; the icon needs its own handler

**Running on tc:** campaign `scratch` at turn ~1945 on `main`, with fork build `565e6f40` (forkLevel 5,
`uiElementStruct:readBytes`; zip sha256 b3548dc3…). Installed 05:36 with `just install-eop-zip`; the turn
loop and crash-watch are up. The runner VM is shut down again.

**What we learned:**
- **The root list tracks the screen.** A 30-minute sampler (`readBytes` on every 47x47 root, every 15 s)
  matched the screenshot's slot count each time. The icons stack 47 px apart from (0, 546), and every one
  has vtable `0x01363b6c`. A cleared icon drops off the list within seconds (0 roots two seconds after a
  scroll was read). So there's no "cleared icon that looks live" to filter out.
- **`execute()` on a live icon crashes the game** (06:08, crash report `runs/crashes/2026-11-20-060924`).
  The list, the check (vtable, size, position) and the press ran in one Lua call, so the icon was live:
  `eax` held its vtable. `useButtonFunc` (`0xb07e00`) does `mov eax,[ecx]; call [eax+0x188]`, which is
  vtable slot 98. The icon's vtable is shorter, and that slot holds the float π (`0x40490fda`, the fault
  address). The 11-19 crash was the same thing, not a stale icon.
- The 04:50 crash is different: it's inside the game (`medieval2.exe+0x2275f0`), not ours. It's still
  untriaged.

**Rule:** never call `:execute()` on anything but a button. It works only for button classes.

**Next (W52):** find the icon class's own click handler. Read the icon vtable at `0x01363b6c` from the exe.
Compare it with a button's vtable (read one live with `readBytes(0,4)` on a `getOpenUiElements` button).
Slots that match are base-class methods, and the icon's overrides are the candidates. Then add a fork
binding that calls only that named slot on an element whose vtable is `0x01363b6c`, and prove it on one
icon. Until then the minimized reopen stays a click.

## 2026-11-19 (14:00): resume after power-off fixed; minimized icons reachable, not yet pressable

**Running on tc:** campaign `scratch` at turn ~1555 on `main` (#651), with fork build 015d2a82 (forkLevel 4; zip sha256 2898a5ae…). The turn loop and crash-watch are up.

**What happened:**
- **The campaign sat idle from the 11-15 23:59 power-off to 11-19 13:20.** Boot-resume fired at 05:44 but logged `just: command not found`, because the autostart's PATH lacks `~/.local/bin`. Fixed in #650. Tomorrow's 03:00 power-on is the first live run: look for "resuming 'scratch'" in `logs/boot-resume.log` with no "failed" after it.
- **#651:** the relaunch fails at once when the game exits while loading. At 13:30 the game hit "unspecified error and will now exit" after the main menu map, and the relaunch waited out its full 240 s.
- **W03/W05 confirmed on live play:** the bridge log has 68 "a marriage offer: pressed … by its element" lines from 11-15. The 16:38 one was the forced probe, and later ones were the game's own offers.
- **W11/W22, the papal election (11-15 17:01):** the ruler voted for candidate 2 of 3, but the notice, the vote and the reopen still went through x-input clicks. Still open.
- **Clicks left since 11-15** (from `logs/scratch-turns.log`):
  - 149 `open kind=minimized`: the stuck-turn reopen (W52).
  - 16 offer icons opened (`open kind=marriage/adoption`).
  - 1 papal vote and 2 notice clicks.
  - The minimized icon is the main click left.

**Minimized icons (W52), where it stands:**
- The fork's `getOpenUiElements` drops root elements, and the icons are roots. Fork #12 (level 4) adds `gameSTDUI.getRootUiElements()`. Live, it listed a 47x47 root at x=0, y=546.
- **`:execute()` on that root crashed the game** (13:54, stack through `useButtonFunc`). The icon had probably been cleared a few seconds before (`clear_messages` at 13:54:02), and a cleared icon has the same size and position as a live one. It may also be that `execute` only suits buttons.
- **Rule: nothing presses a root element until liveness is known.**
- **Next:** the fork commit `0092e57a` (level 5, `uiElementStruct:readBytes`) waits on the runner VM. The VM is shared: ask session uncle-j-s-refinery-5b or the author before starting it with `virsh -c qemu:///system start gitea-win-runner`. Then dump a live icon (just after a message arrives) and a cleared one, compare the vtable (the first dword) and the flags, and press only what passes.

**Lesson:** never walk game memory with raw LuaJIT ffi in the live game. An ffi read of `uiElementList` crashed it at 13:29 (fault in lua5.1.dll). Use a checked fork binding instead.

## 2026-11-15 (17:00): workarounds fixed at their cause, offers answered with no click

**Running on tc:** campaign `scratch` at turn ~1243 on `main` (#648), with our EOP fork build 4d1f3620 (forkLevel 3; zip sha256 925a9306…). The turn loop and crash-watch are up. The Pope was killed by hand at turn 1242 for a papal probe (see item 2), so an election is coming.

**Late fix (#648):** a stuck turn's decision scroll that no request held had its answer written and never pressed (a regression from #645; live at turn 1242). It's now queued as a decision. Live: the ruler declined, the bridge pressed it by element, and turn 1243 began.

**Merged this session:**
- #642–#646.
- Fork #9, #10 and #11.
- Register status: `docs/WORKAROUNDS.md` has 14 rows closed (W03 W05 W12 W13 W15 W21 W24 W25 W29 W32 W37 W47 W48 W53) and W30 in part. The rest are open.

**Proven live on tc:**
- **Offers, pressed by element:** a suitor declined, a suitor accepted and a wife accepted, each married with the game alive 60 s on. The wife accept is the case where a click crashed the game on 11-10.
- **Full loop:** an offer held End Turn, the ruler accepted, the bridge pressed the answer by element, and the man married.
- **W47:** the main-menu map line.
- **W53:** Parley's `uiCfg.json`.
- **W24 and W25:** a window closed by pressing its unnamed seal.

**Pick up here, in order:**
1. **Confirm W03/W05 on live play.** Look for the game's own offer (not a forced one) going through the ruler and being pressed by element, with no `marry_live` line. Search the bridge log for `pressed (accept|decline) on .* by its element`.
2. **Papal election, no click (W11, W22):**
   - England has a cardinal (Alexander), and the Pope (Aczo de Volta) was killed at turn 1242. By turn 1243's end the trace still saw no `papal_election_scroll`.
   - The probe never saw the election: England's turn didn't end while the death notice was open.
   - Next: when `papal_election_scroll` is up, read its structure with `M.open_ui()`. `M.open_ui` currently skips walking papal scrolls; test whether walking one on the tick is safe (the old hang was `getUiElement` during construction).
   - Then press the ruler's candidate (`papal_vote_button` parts) and close the results scroll by element.
   - Remove `kind = "escape"` and the vote clicks in `popups.py`.
3. **The rest of group B:**
   - W11/W22: papal, item 2.
   - W18: End Turn holds for decisions.
   - W19: request sweeps.
   - W23/W31: screenshot reading. This needs scroll text from the fork; the text parts are type 17.
   - W49: the spy-report and mission timers.
   - W52: the minimized-message reopen click and relaunch-on-stuck.
   - Building block: `M.open_choices`, `M.choice_buttons`, and `:execute()` on any part. An unnamed seal closes a window.
4. **Group C** (C++ fixes in the fork) and **group D** (seat quirks: agy, llama-server, schema).
5. **Older items:** France's prompt size, the ransom case, the fleet-merge crash replay, `frozen_rival_offers_nothing`. Also install fork build 4d1f3620 on the main machine's local game; the bridge refuses lower levels.

**Lessons:**
- agy can't see sibling worktrees from its sandbox. It timed out twice, and once tried `rm -rf` on one (the deny rules blocked it). Use Claude subagents for worktree edits.
- Message scrolls (offers, notices) hang from their message icon, a root of its own, not from strat_ui.
- uiElements from the fork compare by address with `==` (not `rawequal`).
- The fake game models both: `FAKE.open_offer`, and `FAKE.closed` for windows found by name but not open.

**Waiting on the author:** posting `_review/eop-upstream-draft-2026-11-15.md` upstream; the marriage-offer questions from 11-06.

## 2026-11-15 (14:15): two crash loops fixed at their cause; workarounds now tracked

- **Running on tc:** `scratch` past turn 1145 on `main` 65c6fc6 and **EOP fork build 8d87d9e3** (has
  `M2TWEOP.forkLevel`; installed with `just install-eop-zip`); turn loop and crash-watch up.
- **Crash loop 1 (turn 1141, 20 crashes, 00612ea6):** two queued attacks on one rebel army; the second
  battle's defender side was emptied under the open panel and every press crashed. #636: one attack per
  target a turn, the later one held to the next turn's start. Proven on the crash save.
- **Crash 2 (turn 1143, 3 of 3, 00c5db34/00c5dc2f):** an attack and an assassination on one captain, who fell
  in the battle. #639: one action per target a turn, attacks and missions alike. Proven on its save.
- **Also:** #637 presses only what the game's open-UI list shows; #638 the turn loop no longer clicks a
  result's check (the bridge is the one closer); #635 reader tests were red on main; fork #8 `forkLevel`;
  #640 the bridge drives only the fork and group A's workarounds are gone.
- **Register:** `docs/WORKAROUNDS.md`, one row per live workaround with its real fix (51 open). Work it in
  group order: A (fork already fixed: W24 open_ui ffi walk, W25 4,012-name scan, W29 dead retrain clicks,
  W53 zip packaging), B (no-click via `getOpenUiElements()`), C (fork C++), D (seats).
- **Crash saves for repro:** tc `mods/parley/saves/crash_t1141.sav`, `crash_t1143.sav`.
- **Quota:** agy's Gemini Argon is spent to 11-21, Opus via agy and Sonnet spent today; Flash works.
- **the main machine's local game** still has an old EOP DLL: the bridge now refuses it until the fork build is
  installed there too.

## 2026-11-15 (08:00): session end; next session picks up "fix everything we can"

- **Running on tc:** campaign `scratch` ~turn 1045 on **our EOP fork build a3e678b9** (fork #1-#4, #6),
  installed 07:45 with `just install-eop-zip`; game, turn loop, crash-watch up; boot resume installed.
  Proven live: `%` overlay text survives, `tile.isLandConnection` reads, queue item 1 readable and n+1 nil,
  `gameSTDUI.getOpenUiElements()` lists finance_scroll and its buttons as uiElements.
- **Next, in order:**
  1. Swap tc to the final `gitea-ci` build (has #5 splitArmy and #7 CI): fetch the newest `build-<sha>`
     release zip on the main machine (token), scp to tc, `just install-eop-zip /tmp/<zip> <sha256>`.
  2. Press click-only scrolls through `getOpenUiElements()` + `:execute()`: get the marriage-offer and papal
     scrolls' button names (stuck turns now log "on screen: ..."; or force a marriage offer on the bench,
     games/qa/family.toml), then a handler that presses the ruler's choice. Closes no-click challenge 5.
  3. Prompt size: France's prompt is 127-131 KB and growing (notes history); cap or summarize it.
  4. Older open items: ransom case, fleet-merge crash replay, frozen_rival_offers_nothing.
- **Lessons:** a probe that opens a scroll must close it in the same call (an open finance_scroll held the
  Turks' AI turn 6 min); the fork zip's eopData/config drops parley.cfg (the swap now restores ours).
- **Waiting on the author:** posting `_review/eop-upstream-draft-2026-11-15.md` upstream (scrub-clean; nothing posted).

## 2026-11-15 (06:45): fixing everything we can (the author: "IF YOU CAN FIX IT, FIX IT")

- **Requirement:** STANDARDS `fix-what-we-can` (top bar) and memory. Workarounds and upstream reports
  are never the finish line for code we can change.
- **The open-UI list, found (no-click challenge 5):** on the Steam exe the global `0x02c2bc2c` is
  `{ uiElement** list; uint16 capacity; uint16 count }` of drawn parts; `uiElement +0x48` is the parent.
  Climbing each part names its window: `finance_scroll` and `siege_scroll(gates_open_icon, siege_end_button,
  siege_assault_button, siege_maintain_button, ...)` were read live. Bridge `M.open_ui()` (#623, #624; ffi,
  VirtualQuery-checked, trusted only when entry 0 is `strat_ui`); a stuck turn with no known popup logs
  "on screen: ...". **Next:** the fork's `gameSTDUI.getOpenUiElements()` (agy, worktree
  `~/src/games/eop-wt-openui`, branch `feat/open-ui-elements`) returns them as uiElements, so their
  buttons can be `execute()`d: the papal vote and marriage accept without a click. Open question: whether a
  window on the list is always shown (siege_scroll stayed listed for minutes while turns played on).
- **Fork fixes (author/M2TWEOP-library on Gitea, base `gitea-ci`):** #2 ImGui text as `%s` (built, merged);
  #3 `tile.isLandConnection`/`isSeaCrossing` restored with 3.3.1's bits (master folds bits 12-14 into
  `seaCrossing`) (built, merged); #4 getBuildingInQueue 1-based (merged); #5 splitArmy returns nil when the
  game didn't split (building). Then: install the combined `gitea-ci` build on tc, bench it, drop the
  bridge's `%` doubling. The bridge is ready for #4 already (#620: probes position n+1).
- **Stale rows found:** restartLua (master runs it every frame; the bridge's console toggle is now 3.3.1-only,
  #621); garrison `army.leader` (game data; master has `settlement.governor`).
- **tc boot (#622):** `just resume-at-boot scratch` is installed on tc: a desktop autostart runs
  `scripts/boot_resume.sh` (just play + just crash-watch unless paused). Proof is the next 03:00 boot:
  read `logs/boot-resume.log`. Off: `just resume-at-boot-off`.
- **Fault catcher (#625):** every reload had logged "unavailable (CreateFileA failed)"; it is 1224
  ERROR_USER_MAPPED_FILE, the launch's catcher still mapping fault.bin. It reads "on" now.
- **Upstream draft v2:** `_review/eop-upstream-draft-2026-11-15.md` (agy, checked; stale rows dropped,
  fork branches named, scrub checks clean). Still needs the author's yes; nothing posted.

## 2026-11-15 (06:00): fix the EOP draft's items in our fork before posting

- **Gap:** the upstream draft (`_review/eop-upstream-draft-2026-11-14.md`) lists EOP bugs we only worked
  around in Lua. Most are EOP C++ we can fix in `../M2TWEOP-library` (Gitea runner build), as
  minorSettlementDb was. Order: (1) ImGui `Text`/`TextWrapped` format string, restore
  `isLandConnection`/`isSeaCrossing`, the getBuildingInQueue fix (already branch
  `fix/building-queue-index`, also on the github remote); (2) splitArmy refuses a non-adjacent target;
  (3) restartLua without the console, garrison leader; (4) papal `getUiElement` hang, adoption offer, open-UI
  list. Not ours: marryWife crashes (game code), Lua-in-VEH (LuaJIT), the 3.3.1 rows (fixed in master).
  Then the post shrinks to PRs plus what we can't fix; it still needs the scrub and the author's yes.
- **tc boot:** nothing restarted at 03:00; the campaign idled to 05:48. Needs a boot-time relaunch.

## 2026-11-14 (19:30): a marriage that crashes the game is skipped; the turn limit past

- **Marriage crash (#616):** the game crashed at 00C4E8BD on turns 506 and 508, each time right after the
  bridge logged "marrying Phillip Hasting" in the turn-start `marry_singles`. Seven other 16-year-olds were
  married fine that day; why his record crashes `marryWife` is unknown (age 16, family, no spouse). The bridge
  now writes the name to `parley_turns/marrying.txt` around the call; a name still there at the next try goes
  on `marry_skip.txt` for good. Phillip was added there by hand (the old bridge wrote no marker). No crash
  since 16:55, through turn 684.
- **Battle hang, 16:47:** the game hung on a battle result (Scotland v Harold Dobes at York), no crash, so
  crash-watch slept. Relaunched by hand. A hang detector is still missing.
- **Watch wake 19:2x, applied 92% to 57%:** honest refusals. Martio Codax chased Portuguese spies
  that had moved off by the time the order ran ("not in sight"), and a move would put York's garrison past
  20 units. No fix. Note: `distance` in `seen_agents` counts from the faction's nearest eyes, not the agent.
- **Past the turn limit:** the report said "ends after turn 225: 0 turns left" on turn 677; the ruler asked
  twice if the counter was broken. It now says the limit has passed and the game plays on.

## 2026-11-14 (16:00): a fleet-merge crash loop broken; merge_units repeats refused

- **Crash loop, turn 457:** England merged fleet Admiral Robin into Admiral John (15:37:35, "done"); the game
  crashed in that AI round three times (15:38 004CA78E, 15:45 121E229A, 15:52), each reload a post-merge save.
  **#614** refuses a fleet merge in validate. Relaunched by hand from `pre_fleet_merge_456.sav` (the turn-456
  backup); the ruler ordered the merge again and was refused; play went past 459. Cause inferred, not proven:
  fits the 11-11 open bug (a seated faction's admiral leaving the game crashes the character pass).
  **Not reproduced on the bench:** `navy/fleet_merge_survives_a_round` (merge straight through
  `M.qa.order`, no guard) passed both ways, a spawned fleet into England's admiral (16:05) and England's
  admiral into a spawned one (16:09), 120 s alive over 6 rounds each. So a fleet merge alone doesn't crash;
  something in that save did (both fleets were one ship each, and the turn before the ruler had tried to
  disband each one's flagship). #614 stays as a cheap precaution. The crash saves are in
  `runs/crashes/2026-11-14-15{3856,4546,5218}/`; next: replay `Autosave-5.sav` there with the merge undone.
- **crash-watch is a user unit** started by `just crash-watch` (`crash_watch_unit.sh`); after its own relaunch
  it can be running as a plain script. My hand relaunch killed it; it was down ~5 min. Stop it with
  `just crash-watch-stop` before a hand relaunch, and check `pgrep -af crash_watch.sh` after.
- **#613** a second `merge_units` on one army a turn is refused (England sent four for garrison:York; the
  watch woke on applied 100% to 73%).
- **UI probe (#610, #612):** no exe name reaches an open scroll; EOP needs a list of open UI elements.

## 2026-11-14 (13:15): noclick reruns finished; navy and siege pass

- **Watch on** (`just watch scratch`, restarted 13:04), crash-watch on, run 11 live.
- **#607** navy `land_on_coast`, `crossing_in_one_turn`: `match = '^land ok'`; both pass noclick with the army
  ashore (12:49, 12:50). **#608** `forced_ai_siege`: the force worked all along; message 39 came 8 s later
  as "popup handled: game message 39"; passes noclick (12:54).
- **diplomacy noclick (09:49):** 11 pass, 4 inconclusive (AI offers), `frozen_rival_offers_nothing` fails
  truly: every AI turn logs "turn still running after 1s frozen; game AI unfrozen until its next turn", and
  an AI offer came at 09:48:02 (sender not logged; Denmark's turn was running at 09:48:20). The bridge declined
  it by `diplomacy_decline_offer_button`, no click. The bench freeze is a 1 s freeze; the case's premise is
  false while that valve stays. Decide: drop the case's claim, or keep the AI frozen past 1 s safely.
- **`forced_own_men_captured`** fails every run since 11-06 (passed 11-06 10:01), clicks allowed or not.
  Ruled out: noclick (fails with clicks, 13:0x); 111715d's unmarried spawned general (married him in setup on
  tc, uncommitted, 13:10: still no ransom). The battle runs (`battle sides` 1u v 1u, auto-resolve, result
  ticked); then events 55 and 217 come and get `clear_messages` (handle_popups, unnamed event, no scroll).
  Next: read the battle's winner and survivors, and test whether 55/217 is the ransom being cleared.

## 2026-11-14 (08:50): no-click push; session ended to load new hooks

The author's goal: no screen clicks anywhere, then a public call to arms for the rest, and EOP fixes sent upstream.

- **State on tc:** run 11 is at turn ~53 (restarted at 06:15 from `scratch_run10_start.sav`). A crash at turn 46
  (07:07, new site: medieval2.exe `00593060` null `this`, called from `00bf4012`, right after England's turn
  start; repro save in `runs/crashes/2026-11-14-070704/`) was relaunched by crash-watch; watch for a repeat.
  **The campaign watch is OFF** (stopped for the bench): start it first thing.
- **A noclick bench rerun was going at session end** (popups, quiet, siege, towns, navy, forced, diplomacy, then
  `just click-census`). Read `runs/qa/` for its reports; rerun what's missing:
  `just qa <suite> kind=noclick` on tc. popups/quiet/siege/towns have never had a noclick report.
- **Merged today:** #595 merge_units pairs as the bridge does; #596 PATH in the justfile; #597 report written on a
  load; #598 `kind=noclick` (every case, clicks refused); #599 bench suitor offers off; #600 land one step ashore
  (+ #604: not-yet-ashore is pending, not refused; #600 alone refused real landings on the bench); #601
  `needs_click`; #602 click census (`x-input:` lines, `just click-census`); #603 force_ai_siege, frozen-AI log
  each turn, the campaign-ender runs last.
- **Bench so far (noclick):** 52 of 65 passed in the 08:22 run, 8 of 8 instant, navy 15 of 18 (the 3 were the
  #600 bug, fixed by #604, not yet re-run). Still failing: `forced_own_men_captured` (no ransom offer; likely the
  battle roll). Inconclusive: the 4 AI-offer cases (no AI offer comes; EOP can't force one).
- **Rerun results (09:00-09:40, after #603/#604):** quiet 4/4, siege 13/13, towns 22/22, instant 8/8 pass with
  every click refused. popups: `papal_election_vote` hangs (the papal vote is click-only: challenge 5; give it
  `needs_click` or solve it). navy: `land_on_coast` and `crossing_in_one_turn` still fail: the land result is now
  "land ok: landing ... ordered; ... the next report says" and the cases expect `equals = "land ok"`; make them
  `match = '^land ok'` and check the army ashore with `within`. forced: `forced_ai_siege` still gets no message 39
  after #603 (open), `forced_own_men_captured` no ransom (open). diplomacy didn't run (session end): rerun it.
- **The challenge list:** `docs/no-click-challenges.md` (this PR): 6 challenges with leads, forcing tools and
  proofs. Live census (one day): 166 message-check clicks, 122 minimized-message reopens, 61 marriage decisions
  (Escape), 13 adoption clicks, 1 papal vote. First census with event numbers: every bench click was an
  acknowledge on message event 40.
- **Next, in order:** (1) start the watch; (2) finish the noclick reruns; (3) the UI probe: with a forced wife offer
  and an event-40 scroll open, `dofile("Z:/tmp/ui_probe.lua")` (tc /tmp: every `*_button/_scroll/_panel/...`
  name from medieval2.exe, `/tmp/ui_candidates.txt`; both are in /tmp and gone after a reboot: rebuild with
  `strings -n 6 medieval2.exe | grep -E "^[a-z_]+_(button|scroll|panel|listview|window)$"`), then wire what
  presses into the bridge (`close_tick_button`, `perform_marriage_button` are the leads); (4) papal: write
  `cardinal.voteFactionID` on a forced election and see if the game keeps it; (5) give the marriage QA cases a
  family groom (`spawnArmy` has a `family` flag) so wife offers can come.
- **Waiting on the author:** the EOP upstream draft `_review/eop-upstream-draft-2026-11-14.md` (14 items, 3 draft issues;
  nothing posted); whether live play should stop marriage/suitor/adoption offers (no clicks, but no suitor choice).

## 2026-11-14 (06:30): the run-10 campaign ended at turn 1447; restarted at turn 5; merge_units fixed

- tc booted at 03:00 but nothing was started (no session). 06:04: synced tc to main, `just play scratch`, `just crash-watch` (relaunched from Autosave-1, turn 1440; its "crash suspected" report at 06:04 is the 23:59 power-off, not a crash), and the watch.
- 06:15: the watch woke `LOST`: the campaign-over scroll during Poland's turn, turn ~1447 (France's note: "five of 45 regions held and no turns left"). Restarted per the 11-11 entry: the run's turn folders (26 GB, turns 5-1447) are in `~/mtw2-scratch-turns-run-to-t1447-20261114` on tc; `just relaunch-game --save scratch_run10_start.sav` (turn 5, no clicks), play, crash-watch, watch.
- This PR: troops in the report carry `armour`, `weapon` and `held` (bodyguard or retraining), from the bridge's own `merge_key`; `validate_orders` and the prompt's merge line group by `Unit.merge_group()`, so a pair the bridge won't merge is refused before it's sent. Live, Captain Gerbert (turns 1440-1441) had the same 64/75 and 67/75 Pike Militia as Foucher and was refused again; France disbanded both before they could be probed, so which field differed is not known.
- Still next: recruits of units a town can't train now (France's second most common refusal).

## 2026-11-13 (06:30): resumed on tc; the watch runs there now

- **11-12, not in the last entry:** tc booted at 03:00 and a turn loop ran 05:24-05:55 (turns 524-562); tc then shut down at 05:55, was up 17:50-18:01, and stayed off until the author powered it on at 06:14 today. The game ended with that shutdown; it didn't crash. Cause of the early shutdown and the missed 03:00 boot: unknown, asked the author.
- 06:17: `just play scratch` and `just crash-watch` on tc; crash-watch relaunched from Autosave-2 (Steam took 112 s). The watch runs **on tc** over ssh: `ssh the test laptop 'cd . && WATCH_BOT=0 just watch scratch'` (`just` is in `~/.local/bin`).
- Haiku's safeguards refused England's prompt on turns 524 and 538 (2 of 39); watching it.
- This PR: a watch started where the game doesn't run exits `NOT HERE` (the first one ran on the main machine and woke on an 11-04 log line).

## 2026-11-13 (23:50): end of day, turn 1430; next: merge_units still gets through

- No crash since turn 1252 (the stale-spouse guard and family-only marriages are in). tc powers off at 23:59.
- **Next session, first:** the merge_units check (#593) doesn't catch every case. 23:00-23:47 France still sent it 14 times on Captain Foucher, whose report shows two worn Pike Militia (64/75, 67/75), so it passes; the bridge groups units by type **and armour and weapon level** and refuses. Fix: put each unit's armour/weapon level (or the bridge's own "can merge" answer) in the report's troops, and check that in `validate_orders`. France's applied share fell to 50% on this, with recruits of units a town can't train now (Naples, Vienna: Pike Militia) second.

## 2026-11-13 (22:40): merge_units checked before the bridge sees it

- Watch wake (France applied share 82% to 60%): 21 of France's refused orders since 22:00 were `merge_units` on Captains Anseau and Robert, which the bridge refused every turn ("no two worn units of one type"). `validate_orders` now refuses it up front when the report shows no two under-strength units of one type (skipped when a unit's maximum is unknown), so the ruler hears it at once. Bench: `test_merge_units_needs_two_worn_units_of_one_type`.
- No new marriages since 21:48 (the family-only fix); the scan still clears stale spouses of earlier wives (5 more by 22:21), no crash.

## 2026-11-13 (21:50): what freed the spouses: Parley married agents

- 21:00-21:27 the new scan cleared 5 stale spouses, no crash (to turn 1311). All English wives of freed husbands; the first, Michell Higgines, is an **assassin** the bridge wed at 20:49 (`single men married ...: 1 (Michell Higgines)`). `M.marry_singles` (#519, 11-06) married every single adult man, agents and captains included; the game offers wives only to family men, keeps family records, and frees an agent's record at his death, leaving his wife's `spouse` dangling.
- **Fix (this PR):** `M.marry_singles` and `spawn()` marry family men only (the 11-06 note in games/qa/family.toml named this as the fallback). The stale-spouse scan stays as the guard for wives already made.

## 2026-11-13 (21:20): the 00eff4db crash named: a natural death's message reads a freed spouse

- Turn 1252 crashed at eip 00eff4db (`runs/crashes/2026-11-13-203639`), the third time (11-11 t272, 11-13 t640), and the bridge's catcher had the stack this time. Chain: 0x5a807c (sets characterRecord `deathType` = 1 natural, death year/season) → 0x8344c0 → 0xc4dec0 (message type 0x4f) → 0xc48a50, which copies the record's name (+0x4), then its spouse's name (+0x228 `spouse`, `[spouse]+4`) with 0xeff4d0, the ref-count copy; the spouse record was freed (its string rep read 0). Offsets checked against EOP's `types/characterRecord.h`.
- Live scan right after a relaunch: 6449 records, 3672 married, **0** spouses outside the factions' lists. So it builds up in a session (the crashes came 180+ turns after a load).
- **Fix (this PR):** `M.stale_spouses()` at every faction's turn start (19 ms): a spouse pointer (compared by address, never followed) that no faction lists is set to nil, which the message code handles; the log says `stale spouse cleared: <faction>'s <name> ... last seen as <spouse> (<faction>)`. Bench: `test_a_spouse_no_faction_lists_is_cleared_and_named_from_the_last_scan`.
- **Next:** the log lines say who the freed spouses were; that names what frees them (a guess: a bribed or defecting character's old record, `deathType` bribed). Repro save: `mods/parley/saves/crash_t1252.sav`.

## 2026-11-13 (18:55): "Captain X" found the fleet "Admiral X"

- Watch wake (TREND: France's applied share 89% to 67%): turns 1177-1180 France's `march_on "Captain Thibault"` came back "is a fleet". `find_army_now` matched ids with `same_army_id`, which drops the Admiral/Captain title, and the fleet "Admiral Thibault" came first in getStack order. Fix: an exact id match first, the title-stripped one after. Bench: `test_a_captain_is_found_before_an_admiral_of_the_same_name`.
- No crash since the agent-mission fix at turn 1074 (to 1180 so far).

## 2026-11-13 (16:45): turn-1072 crash: a mission against a captain the same turn's bribe won over

- Turns 940-1071 ran on the EOP fork build with no crash. At 1072 the game executed heap memory (c0000096 PRIV_INSTRUCTION, eip 340352d8; `runs/crashes/2026-11-13-162504`): England's orders sent diplomat John Watkins to bribe Spain's Captain Americo and assassin Algonso Pontferrada to kill him. The bribe won Americo over at 16:24:22; the assassination then ran on the defected captain and the game crashed. crash-watch's relaunch replayed the same two orders: the bribe failed, the assassination went ahead, no crash.
- **Fix (this PR):** one agent mission per target per turn, in `validate_orders` (the ruler is told) and in the bridge's `agent_handler` (any path). Bench: `test_one_mission_per_target_per_turn` in test_validate.py and test_lua_bridge.py, both fail without it.
- Repro save: `mods/parley/saves/crash_t1072.sav` (turn 1072 start); the bribe's success is a roll, so a forced repro would need the bribe made certain.

## 2026-11-13 (13:50): tc runs our EOP fork build with the minor-settlement cache fix

- **What:** the author's fork `author/M2TWEOP-library` PR #1 (merged into `gitea-ci`, `4c8a0743`): `minorSettlementDb::clear()` at every `preFactionTurnStart` and every `postBattle`, so the cache rebuilds from live lists instead of keeping freed settlement pointers (the turn-812 and 11-11 turn-265 crashes). Built by run 709; the zip is the pre-release `build-553d2c46ca94990b2d0879b64f38a06fb56fb775` (releases API, token works).
- **On tc** since turn 940 (13:44): `mods/parley/M2TWEOPLibrary.dll` + `.pdb` from that build (dll sha256 `aab15ebd742f4c97...`). The upstream master b525628 files are kept as `*.bak-b525628` next to them. **Rollback:** stop crash-watch, copy the `.bak-b525628` files back over, `just relaunch-game`.
- **Caution:** tc never ran EOP 3.3.1 (that tag has no `minorSettlementDb`); it ran upstream master b525628. `just install-eop` would put upstream back and drop the fix. Making the installer fetch the fork build is the follow-up.
- CI note: Gitea's API can't list Actions artifacts and the job token can't write packages, so the fork's build publishes each zip as a `build-<sha>` pre-release.
- Upstream report (EOP-Labs) is the author's call.

## 2026-11-13 (11:40): three more crashes after resuming at 805, two kinds

- **808 and 809: `medieval2.exe 00612ea6`**, right after auto-resolving a battle. The game reads `battle.sides[i].armies[0].army` (null in that battle) and then that army's `+0x100` settlement. EOP's layout: battleData `sides[8]` at `+0x9c`, side `armies[64]` at `+0x58`, battleSideArmy `stack` at `+4`. The relaunch at 11:27 played past it, so the crash isn't strictly deterministic. **This PR** logs `battle sides: ...` (each side's armies) before every auto-resolve press, so the next one names the empty side. If a side is empty before the press, the fix is to not press (a guard in `M.on_pre_battle` / `watch_buttons`).
- **812: inside EOP**, `minorSettlementDb::getSettlement+0x50`, called from `aiGlobalStrategyDirector::initialize2` -> `aiMilitaryDirector::initialize` -> `aiCampaignController::isDefensive`. That's EOP's replacement of the game's campaign AI, and `getEopAiConfig().enabled = false` (#574) doesn't gate it (the "naval target ... score" lines are the same code). Cause, from EOP's source: `regionMinorSettlements` is a pointer cache filled by `load()` at game load and cleared only by `onExitToMenu`, new game, save load, and post-battle when `campaignData->type == 3`. A minor settlement that changes hands otherwise leaves a dangling pointer. Same family as the 11-11 turn-265 crash. A real fix is in EOP (clear or validate the cache on settlement events): The author's fork `games/M2TWEOP-library` (branch gitea-ci) or upstream. **For the author.**

## 2026-11-13 (11:15): turn 804 crashed every time; campaign resumed at 805 from a trial save

- **The crash:** `medieval2.exe eip=0070f5f9`, in France's turn start. The catcher's stack runs from the character loop (`0x4ffcfe` calls `0x5a2eb0`) to `0x5a2bd2`, then the wrapper `0x70f690`, then `0x70f5f0(this=NULL)`, which reads `+0xf0/+0xf8` (in EOP's armyStruct, the character list and its count). In the `ebp==2` branch at `0x5a2b51`, the character being processed (`esi`) has a null `+0x100`, and the object looked up for it (`edi`, from `0x4c9750`) has a null `+0x100` too (armyStruct `+0x100` = settlement).
- **Who:** `esi = 0x1015e260` is **France's assassin René de Bordeaux** at (112,100), with no ruler order of his own. Matched by address after loading `crash_t804.sav` (saved on tc in mods/parley/saves). `edi = 0x1e341fc0` matched nothing at load; it's made or moved during the turn.
- **Not a single order:** France's turn-803 orders were 6 merges into garrisons + 3 ship disbands. The full set crashed 3 of 3 from `crash_t804.sav`; disbands alone, merges alone, and either half of the merges with the disbands all played on. Like the admiral crash, the orders shift the game's dice and only this exact sequence reaches the fault: a game/EOP bug in an agent's turn-start action, with Parley only steering the RNG.
- **Recovery:** the turn-803 autosave was overwritten by the trials, so play resumed from trial 6's turn-805 save. France's disbands and its Bruges, Toulouse and Florence merges went through there; the Paris and Venice merges didn't (Genoa's was refused at 21 units anyway). France re-planned from its 805 report.
- **Next for this one:** name `edi`. The way the admiral crash was named: the machine-code handler calls a Lua callback for this one AV only (`~/mtw2-crash-bisect/fault-tools/`), from `crash_t804.sav` with the full orders. The orders, the address-matching Lua (`who.lua`) and the fault.bin are in `~/mtw2-crash-bisect/t804/` on tc.
- Pitfall: a hand-made `paused.txt` (no reason in it) isn't lifted by `just play`; remove it by hand.

## 2026-11-13 (10:40): rotation made crash-watch kill a healthy game (fixed)

- 10:24, turn 794: rotation moved the 21 MB bridge log aside mid AI turn; with no log, crash-watch's age was "since midnight" and the busy game missed its probe, so it was relaunched (Autosave-1, no clicks). Fixed in this PR. Watch wakes earlier this morning were trends only: France lost Cagliari (714, to rebels) and Edinburgh, Angers, Valencia, Tunis (774-781; Spain took three); England's applied share dipped on fair refusals.

## 2026-11-13 (09:00): turn 705 died of c0000417; the catcher takes every error exception

- 08:41:48, turn 705: msvcrt `_invalid_parameter` raised `c0000417` the same second the bridge logged "autoplay: ending turn 705". Not an access violation, so neither the catcher nor the report's Proton line saw it. Both now take any 0xC... exception (this PR).
- **Read stacks with care:** `click_end_turn()` runs the whole AI round inside the bridge's Lua call, so every crash during the AI turns has lua5.1.dll and M2TWEOPLibrary.dll frames on the outside of its stack. Those don't make Lua the cause; look at the innermost medieval2.exe frames.
- The catcher installs once per game process: a new stub needs a game relaunch, not `just reload-bridge`.
- **Cause found (same PR):** the catcher's stack, named with EOP's pdb (`scripts/pdbsym.py <pdb> <dll> <rva>...`, a standard-library S_PUB32 reader; no llvm tools on either machine), went sol -> `ImGui::TextWrapped` -> `ImFormatStringToTempBufferV` -> ucrtbase. The overlay hands the ruler's note to TextWrapped as a printf format, and England's note had "80%." (invalid). 512 earlier notes had a "%" that happened to parse. Fixed by `bridge.imgui_text` (doubles `%`); acceptance is turn 705 replayed from Autosave-2, which crashed 3 of 3 before.
- Worth telling EOP upstream: its Lua `ImGui.Text`/`TextWrapped` bindings pass the string as the format.

## 2026-11-13 (08:30): turn 640 crashed at 00eff4db again; the bridge now catches the stack

- 07:34, turn 640: `eip=00eff4db`, the same address, esp and ebp=0 as turn 272's, 0.18 s after EOP's "Faction turn start: slave". The code is a ref-counted handle copy (`addw $1,(%ecx)` through a null handle) with 1373 callers in medieval2.exe, so only the stack can name the caller. Crash-watch recovered it with no clicks.
- **The fault catcher** (CHANGELOG): every crash report now carries the faulting stack (`fault-stack.txt`, `stack:` in report.md). Next time 00eff4db fires, read the medieval2.exe return addresses there and look them up in a disassembly made on tc with `objdump -d medieval2.exe > /tmp/m2.dis` (tc's nightly power-off may clear /tmp). Kill switch: `fault_catcher=0` in bridge.txt.

## 2026-11-11 (23:50): session end; the campaign is paused for the night at turn 523

**State:** the test laptop is on main #578. The 23:45 night stop ran `just stop` (paused.txt written) and `just crash-watch-stop`. From turn 274 to 523 there were no crashes. England was still in the game at the stop.

**Next session, in order:**
1. Resume on tc: ship any newer main by bundle (tc has no Gitea route), then run `just play scratch`, `just crash-watch` and `WATCH_BOT=0 just watch scratch` in the background.
2. On each watch wake, fix the cause end to end.
3. Still unexplained:
   - Why an admiral's death crashes the game (#564 only avoids it).
   - Denmark's turn-106 freeze.
   - The one-off fault at 00eff4db (turn 272).

**For the author:** the admiral age cap (#564), England's ruler quality (it lost the 307 and 214 campaigns), and EOP AI off (#574).

## 2026-11-11 (20:05): merge_units says what it would combine (#578); turn 272 crashed once

- **#578.** At 18:47, on turn 179, the watch's applied-share alert fired.
  - The cause: England ordered `merge_units` on 5 garrisons, and the game refused all 5 with "nothing to merge". Each garrison had only one worn unit of a type, next to full ones. The ruler's note said "a refusal costs nothing".
  - The fix: any army with a worn unit now gets a line saying what a merge would combine, or "would combine nothing (refused)". Retraining already had a line like it. The turn loop was restarted on #578.
- **Turn 272 crash (19:58).** Proton's log shows `c0000005` at eip=00eff4db, an address no other crash has had. Crash-watch relaunched from Autosave-3 with no clicks, and the campaign was on turn 274 by 20:00. That's a one-off like turns 46 and 56, so no separate fix. The report is `runs/crashes/2026-11-11-195801` on tc. If that address comes back, get the stack with the machine-code exception handler (`~/mtw2-crash-bisect/fault-tools/`).

## 2026-11-11 (16:05): England lost again at turn 214; restarted at turn 5

Turns 124-214 had no crash with EOP's AI off (#574). At turn 214 England held only Caen, and the game showed "Victory Conditions Failed" again. The bridge pressed its one button and the game went to the main menu. **#567 caught it**: crash-watch relaunched by itself 46 s later and the game played on to 215. That's play after a declared defeat, so per the standing order the campaign was restarted at 16:03 from `scratch_run10_start.sav`. The run's turn folders are in `~/mtw2-scratch-turns-run-to-t215-20261111` on tc.

**For the author:** England's ruler has lost both of today's campaigns: one ended at turn 307 (it showed the defeat scroll at 271 first), the other at 214. That's a question about ruler quality (the seat and its prompt), not a fault the bridge can fix.

## 2026-11-11 (14:35): EOP's campaign AI off again (#574): it crash-looped turn 124

Turn 124 crashed **3 of 3** from the same autosave at the same instruction (`medieval2.exe` eip=007193cf, same esp) in Denmark's turn, right after EOP's campaign AI logged "Try attack settlement order ... moveTactical: can not move army". With the AI switched off after the load it played on to turn 125. A `control.txt` lua line didn't count: it ran during the start-up load, and the campaign load turned the AI back on. **#574** sets it at every load: off unless bridge.txt has `eop_ai=1`. The admiral cap (#564) stays. tc is on #574, turn 128 at 14:35, with crash-watch and the watch running.

**For the author (replaces the two questions above):**
1. EOP's campaign AI is **off** (#574): it crash-looped the campaign. `eop_ai=1` in bridge.txt brings it back.
2. England's admirals don't die of old age (#564): a workaround for a game/EOP bug. OK for now?

## 2026-11-11 (14:25): the new campaign's crashes and stalls, all recovered

Since the restart at turn 5 (12:06). Each crash has its report in `runs/crashes/` on tc.

| When, turn | What | Where | Recovered by |
|---|---|---|---|
| 12:53, 46 | crash, `eip=00bf3a84` | game code; a papal election was under way (bridge's papal tick last) | crash-watch |
| 13:58, 106 | Denmark's AI turn stood still after a battle, nothing on screen | unknown | hand relaunch; now crash-watch at 20 tries (#572) |
| 14:21, 124 | crash, `eip=007193cf` | game code, right after EOP's campaign AI logged attack orders ("moveTactical: can not move army") | crash-watch |

Together with 11:08's turn-265 crash inside EOP's `minorSettlementDb` (EOP AI naval scoring), 2 of today's 4 non-admiral faults came while EOP's campaign AI was issuing orders. That's evidence for the author's open call on EOP's AI, not proof. Also merged: #570 (watch: a stuck line from before a load is stale), #571 (trends: an answered but unapplied turn isn't a fall), #572 (crash-watch: relaunch a turn stuck 20 tries).

## 2026-11-11 (12:07): England lost the campaign; restarted at turn 5

The game's campaign-over scroll ("Victory Conditions Failed: your faction has been conquered") came at turn 271 and again at 307, during Scotland's turn. England had held only Nottingham since at least turn 271. Another faction presumably met its victory condition, which ends the player's campaign. This is the standing order's "loss", so the campaign was restarted at 12:06 from `scratch_run10_start.sav` (turn 5). The lost run's turn folders (5-307, and today's `_old-timeline-20261111`) are in `~/mtw2-scratch-turns-run-to-t307-20261111` on tc. Turn loop, crash-watch (#567) and the watch are running; the 23:45 stop timer is set.

## 2026-11-11 (10:55): the crash is England's admiral dying of old age; his age is capped; campaign replays from 246

**State:** tc on main (#564). The live campaign was restarted at 10:49 from `crash_t246.sav`; the log says `england: Admiral Richard's age held at 50 (was 63)`. The turn loop, crash-watch and `WATCH_BOT=0 just watch scratch` are running. Turn folders 246+ from the old timeline and today's trials are in `parley_turns/scratch/_old-timeline-20261111/`. A transient timer (`parley-night-stop`) runs `just stop` and `crash-watch-stop` at 23:45.

**Cause, as far as shown.** When a seated faction's admiral leaves the game, the next round's start crashes. England has one admiral, Admiral Richard (66 at turn 252). The game returns to `eip=0` in England's turn-start character pass (`medieval2.exe` loop at 0x4f8011, calling 0x597c60), on the new admiral it made in his place ("Admiral Thomas"). That happens right after the rebels' turn ends and the year's births are rolled. Old age is a dice roll. Parley's presence changed the game's RNG, so it decided whether he died that year. That is why every crash-rate split looked like a dose effect, EOP's AI (#562) included.

| resume_t252.sav | Crashed |
|---|---|
| **no Parley**, untouched (he survives the roll) | 0 of 2 |
| **no Parley**, Admiral Richard killed at load | 2 of 2 |
| **no Parley**, his ship removed with him aboard | 2 of 2 |
| **no Parley**, the HRE's admiral killed / England's merchant killed | 0 of 2 / 0 of 2 |
| stock bridge, untouched | 6 of 6 |
| bridge, Richard held at 30 | 0 of 3 |
| **shipped #564** (t252 / t247 / crash_t246 with EOP's AI on) | **0 of 4 / 0 of 3 / 0 of 8** |

**Merged today:**
- **#561:** crash reports keep Proton's log around the fault (`proton.log`, `meta.fault`).
- **#562:** EOP's campaign AI off. **Reverted by #564**: its 0 of 16 was the same dice.
- **#564:** `M.spare_admirals` caps a seated faction's admirals' age at 50, at every load and each of its turn starts. It's a **workaround**: battle or assassination can still take an admiral and crash the game.

**Open bug (game or EOP, not Parley):** why the replacement admiral crashes. It happens only for the seated (England) admiral. Nothing is aboard his one-cog fleet, which is at sea at (109,142). EOP's `onNewAdmiralCreated` never fires before the fault. Next probes: give England a second admiral, then kill Richard; and do the same on a fresh campaign, to tell this save from the game.

**How it was found** (tools in `~/mtw2-crash-bisect/fault-tools/` on tc; memory note *bisect-crash-by-building-up*):
1. Proton's SEH log gave the fault.
2. An x86 machine-code vectored exception handler wrote CONTEXT plus the stack to a mapped file. For that one access violation it then called a Lua callback, which named England's characters at the fault. A Lua handler entered on every exception corrupts LuaJIT.
3. `M2TWEOPLibrary.pdb` and `objdump` named the code.

Withdrawn today: GC, End Turn timing, the JIT and EOP's AI. None was the cause.

**11:08, turn 265: a different crash, in EOP's own code.** EOP's `minorSettlementDb::getSettlement(int, int)` (`types/strategyMap.cpp:104`, `M2TWEOPLibrary.dll+0x7d0f72`) read out of range (`0x6FA50E7C`). It happened during the Papal States' turn, while EOP's campaign AI logged its naval-target scoring. Parley never calls minor-settlement lookups. Crash-watch relaunched, and the same turn passed, so it isn't deterministic: once in about 20 rounds. Report: `runs/crashes/2026-11-11-110813` (its `meta.fault` came from #561). If it recurs, turning EOP's AI off (#562's code) would avoid it, at the cost of how AI factions play.

**11:13, turn 271: "Victory Conditions Failed".** A game scroll ("Your faction has been conquered…", one button: Return to Main Menu) came while England still held its towns, and the bridge pressed its only button. The campaign went to the main menu, and nothing noticed for 15 min. A relaunch from turn 271's autosave played on to 273 without the scroll, so it's not a fixed end date. Why it fired is open; the capture is `parley_turns/scratch/captures/popup-271-1331220.png`. **#567:** crash-watch now relaunches when the game has left its campaign for the menu (`scripts/left_to_menu.sh`).

**For the author:**
1. England's admirals can't die of old age while seated (#564); EOP's AI is back as it was. EOP's AI crashed once in its own code (turn 265, above). Off or on is your call.
2. The campaign went back six turns, to 246.
3. The bridge doesn't post to Discord from tc (no bot token there), so these notes are the update.

## 2026-11-11 (09:05): ~~the turn-246 crash was EOP's own campaign AI~~ (wrong: see 10:55)

**State:** tc on main (#562). The live campaign was restarted at 08:59 from `crash_t246.sav`, with EOP's AI off. Round 246 passed, and turn 247 is being played. The turn loop, crash-watch and `WATCH_BOT=0 just watch scratch` are running. Turn folders 246+ from the old timeline are in `parley_turns/scratch/_old-timeline-20261111/`. A transient timer (`parley-night-stop`) runs `just stop` and `crash-watch-stop` at 23:45.

**Cause.** The game returned to `eip=0`, with a zeroed frame, about 0.5 s into the rebels' turn. It was in its per-faction character pass (`medieval2.exe` loop at 0x4f8011, calling 0x597c60), with England's faction and a character on the stack. That happens when **EOP's own campaign AI** (`globalEopAiConfig`, on by default, from EOP's `campaignAi.cpp`: army merges, aux-general transfers, attack orders) has re-created a Timurid captain. Bodonchar's object at the rebels' turn start was new in the crashing run and the old one in the five that passed. Parley's EOP calls only changed how often that AI path came up. That is why every crash-rate arm looked like a dose effect.

| From crash_t246.sav (same flow) | Crashed |
|---|---|
| EOP AI on, all of 11-11 | 11 of 28 |
| EOP AI on, same-session baseline | 3 of 8 |
| **EOP AI off** (experiment patch, then the shipped #562) | **0 of 16** |
| resume_t247.sav / resume_t252.sav, AI off | 4 of 4 / 6 of 6: the bad reference is already in those saves (at 252, a zeroed character block). They were made after round 246 was passed with EOP's AI on. Don't use them. |

**Merged today:**
- **#561:** crash reports keep Proton's log around the fault (`proton.log`, `meta.fault`).
- **#562:** `setup` sets EOP's campaign AI at every load. It's off unless bridge.txt has `eop_ai=1`, and the log says `EOP campaign AI: off (was on)`.

**How it was found** (tools in `~/mtw2-crash-bisect/fault-tools/` on tc; see the memory note *bisect-crash-by-building-up*):
1. Proton's SEH log gave the fault.
2. An x86 machine-code vectored exception handler, installed through LuaJIT ffi, wrote CONTEXT plus the stack to a mapped file. A Lua handler doesn't work: it re-enters the VM on every LuaJIT error exception and corrupts it.
3. `M2TWEOPLibrary.pdb` and `objdump` on the exe named the code.
4. Heap addresses repeat between runs, so a Lua dump of character addresses named the object.

The morning's crash-rate conclusions are **withdrawn**: GC, End Turn timing, the JIT. Each was a 0-of-4 that later trials overturned.

**Next:**
1. Watch the replay through 252 and beyond.
2. Prove it over more rounds: the A/B is 0 of 16 against 11 of 28 on one save.

**For the author:** AI factions now play the game's own campaign AI, without EOP's AI patches (#562). `eop_ai=1` brings them back. And the campaign went back six turns, to 246.

## 2026-11-10 (22:50): the bridge's crash is narrowed to its per-frame tick; campaign parked at turn 252

**State at the stop:** tc on main (#557), stock bridge installed, game loaded at turn 252 from
`mods/parley/saves/resume_t252.sav` (the 20:47 crash's autosave; it crashes there too, 2 of 2), paused,
no turn loop, crash-watch stopped. Turn 252 crashes the same way as 246: the campaign can't go on under
Parley until this is fixed. (Turn 246 was passed once with the no-Parley plugin; that is not a way to run.)

**A clean harness** (on tc: `~/mtw2-crash-bisect/harness.tar`, extract into /tmp; `cut_run_gc.sh`,
`tt_run.sh` and `trials_nopoll.sh` run the arms): a plugin with no Parley
handlers that ends the turn from its own timer, plus only the pieces under test.

| From crash_t246.sav, harness arms | Crashed |
|---|---|
| no Parley code | 0 of 8 |
| + `bridge.setup()` only | 0 of 4 |
| + setup + `bridge.tick()` every 2 s | 3 of 4 |
| + setup + tick cut after `control()` / pause check / UI scans (GC running) | 4 of 9 |
| the same cuts with `collectgarbage("stop")` | 0 of 8 |
| tick cut after reading the `currentFaction` pointer, GC stopped | 0 of 4 |
| tick cut one step later (reads `isPlayerControlled`, then runs the human-turn path), GC stopped | 4 of 4 |
| full tick, GC stopped | 4 of 4 |

The arms that passed with the GC stopped all returned before the tick's **human-turn path** (England's
turn right after the load: apply_orders, ui_jobs, pending_rulers, the holds, click_end_turn). Tried and
not the cause (each still crashed with the GC stopped): never reading `currentFaction` outside the human
turn (branch `fix/tick-reads-no-current-faction`, local only, not merged: not proven), skipping
`watch_ai_turn`, no reads of the rebels' faction, no orders at all, setup's game writes
(auto-resolve option, marriage limits). In full Parley the counts for every single change were 35 of 36
crashed (the 20:45 table's "23 of 25" was undercounted).

**23:00, the human-turn path cut step by step** (harness, GC stopped, the harness timer ends the turn
10 s after the load): cut before `apply_orders` 0 of 3, after `ui_jobs` 0 of 3, after `pending_rulers`
0 of 7, after the holds (everything but autoplay's own End Turn) 2 of 7. The full tick, where autoplay
presses End Turn about 1 s after the load, crashed 4 of 4. The holds are pure Lua table checks, so the
2 of 7 is likely noise. The remaining suspect is **autoplay's End Turn itself, or how soon after the load
it comes**. Note the full-Parley "paused, End Turn from Lua 1 s after the load" arm passed 2 of 2 (with the GC
running), so timing alone isn't settled either.

**Next:** harness, GC stopped, full tick, autoplay's End Turn held 10 s after the first tick
(`patch_late.py` in the harness tar; the 23:08 run of it was broken, because the timer plugin ended the turn first).
Compare that with the full tick, 4 of 4. Then the GC path, which is separate (the cuts crashed 4 of 9 with
it running).

## 2026-11-10 (20:45): a turn-246 crash the bridge causes, repeatable; cause not yet found

**Repro on tc:** `mods/parley/saves/crash_t246.sav` (also `runs/crashes/2026-11-10-185221/`). Load it and
end turn 246. The game dies at the end of the round, right after the rebels' (slave) turn ends, 16-20 s in.
Scripts for each trial: `/tmp/trials_nopoll.sh`, `/tmp/min_run.sh` and siblings on tc (copies in this
session's scratchpad; not in the repo).

| Setup (from crash_t246.sav) | Crashed |
|---|---|
| No Parley code (a 25-line plugin that only ends the turn) | 0 of 8 |
| Stock bridge, autoplay, no Lua polling | 5 of 5 |
| Autoplay variants: no orders / no move / % out of the note / overlay off / GC stopped / all event handlers off / turn start+end handlers off / tick idle between turns / UI scans and sweep skipped | 23 of 25 |
| Bridge paused, the turn ended from Lua | 4 of 14 |
| Bridge's per-frame `on_frame` replaced (events and setup kept) | 1 of 3 |
| Autoplay held 12 s after the load | 2 of 4 |

So the bridge raises the crash rate from 0 to nearly 1 on this save, and no single handler explains it. The
per-frame tick on England's turn (autoplay) matters most. Also seen live on turn 231 (18:38). The campaign
passed 246 with the no-Parley plugin for that one round, then resumed under Parley from
`resume_t247.sav` (20:42).

**Next:** bisect the tick's England-turn path (apply_orders with no orders, ui_jobs, pending_rulers, the
holds, click_end_turn), and `setup` (game options it sets at load), with 5+ trials per arm. One trial
proves nothing here: the "paused" arm passed 5 of 5 before it crashed 4 of 14.

**Also fixed tonight** (each merged, tests green, live on tc):
- **#553:** the watch wakes with `OUT` when another seat's reports stop (France was conquered on turn 169
  and nothing woke for 40 turns).
- **#554:** a disband of the unit its commander rides says so (England ordered "disband the cog" of a
  one-ship fleet 22 times).
- **#555:** `just play` sets the old turn log aside instead of emptying it (it wiped the record of two crashes).
- **#556:** `just probe` installs where the bridge is. Before, it never replaced the bridge, so no "probe"
  run was a no-Parley split.

## 2026-11-10 (17:10): five fixes live since the restart; papal-check crashes open

**Fixed and proven live** (tc on main #550):
- **#547:** an accepted wife offer is closed with Escape, then the bridge marries him (`M.marry_now`). Before,
  the accept click crashed the game (15:23). Not yet seen live.
- **#548:** the first turn start after a load marries nobody. An offer open in the save isn't in `pending`,
  and marrying its man crashed the game twice (Arthur Fowler, 15:25 and 15:31). Live 15:47.
- **#549:** `find_tick` looks inside the scroll only. Green province borders beside the scroll had hidden the
  papal notice's check, and End Turn stuck 10 min on turn 126. Live 16:41.
- **#550:** recruits due more than 20 turns ahead are dropped. They were stale from before the restart and
  made Nottingham's queue read full for good. Live 16:58.

**tc config (not in the repo):** `fallback = "claude:sonnet"` for both seats, since Haiku's safeguards refused
England's turns 140-142 (0 orders each). Sonnet is asked only when Haiku fails a turn; the author moved off Sonnet
10-29 for the usage cap.

**Open: crashes after the papal notice's check is clicked.** At 14:50 (turn 44) and 16:54 (turn 135) the
game crashed seconds after "asking for its check" and the click. The replay went through both times, and
other check clicks (16:41, 16:43) didn't crash. The check is a mouse click, and it opens the election.
Candidates for a no-click route:
- Return/space on the notice, as Escape answers a decline;
- an EOP call that starts the election.

Neither is tried; it needs a bench case (`games/qa/popups.toml` has the notice).

**Open:**
- France's applied share swings with its renamed armies (its AI is unfrozen 1 s into its turn). That's the author's call.
- One-off crashes: 16:12 (turn 110, after England broke an alliance and besieged in the same turn), 10:21, 12:25.

## 2026-11-10 (14:20): a second save the game can't play past (France's turn 271); campaign restarted at turn 5

**Crash, same kind as turn 147:** from turn 271 every replay crashed in France's AI turn, with the game's own
"unspecified error" box. Reports are `runs/crashes/2026-11-10-1252*` through `-1401*` on tc. The bridge's last
lines are always France's spies, "partly successful". Splits on the repro save `mods/parley/saves/crash_france_t271.sav`
all still crashed:
1. France's freeze off.
2. No Parley orders for France.
3. **No Parley Lua at all** (`just probe`, End Turn pressed through the probe).
4. The probe, with four French characters named Saisset/de_Poitiers killed.
5. EOP's own campaign AI off (`M2TWEOP.getEopAiConfig().enabled`; it was **on**, and Parley never sets it).

So, as at turn 147, the game or EOP core can't play the turn. Saves are in `~/mtw2-saves-france-crash-20261110`.
Earlier one-off crashes (10:21 turn 99, 12:25 turn 249) were also in France's turn and didn't repeat.

Next: an upstream report with both repro saves, and the EOP AI as a suspect worth a whole-campaign A/B (off
from turn 1).

**Open, set_tax:** Nottingham read `normal` in England's reports on turns 262-270 after `high`/`extortionate`
orders. The probe at 13:38 read it as 2 (high) in the game, so the write lands. Something sets it back before
the next report, or the report reads it wrong. #544 only catches a write that doesn't land, which isn't this.
Next: probe the level at England's turn start, before the report.

**State 14:20:** the campaign was restarted from `scratch_run10_start.sav` (turn 5). The old run's turn folders
from turn 5 on are in `~/mtw2-scratch-turns-run-to-t271-20261110`. Crash-watch, the loop and the watch are
running, and tc is on main #545. Lesson: stop crash-watch before `just relaunch-game` by hand. Otherwise it
reads the kill as a crash and relaunches the newest autosave.

## 2026-11-10 (09:20): a save the game itself can't play past (rebels' turn, turn 146-147)

**Crash, new kind, not Parley's code now:** from turn 146 the campaign crashed 4 times out of 4 at the end of a round
(08:43, 08:50, 08:56, and a replay; reports `runs/crashes/2026-11-10-0843*`, `-0850*`, `-0856*` on tc). The
game's own "unspecified error" box. Its `mods/parley/logs/system.log.txt` ends at `Faction turn start: slave`,
i.e. in the rebels' turn; the bridge's last lines (England's famine batch) are only the last events before it.
Split, both on the repro save `mods/parley/saves/crash_rebel_turn_t147.sav`: (1) the disaster handler off: still
crashed; (2) **no Parley Lua at all** (a plugin script that only presses End Turn): the log still stops at
`Faction turn start: slave`. So the game or EOP core can't play the rebels' turn from that state. Not yet known:
whether Parley's earlier actions (EOP marryWife wives, merge_armies, France's AI freeze) built that state. Next:
read the rebels' armies/characters in the repro save for something odd; try the repro on a vanilla EOP campaign
setup; consider an upstream report. All six autosaves kept in `~/mtw2-saves-rebel-turn-crash-20261110` on tc.

**State 09:20:** live run restarted from 11-06's kept save (`parley_keep_scratch.restored-20261106-115556.sav`,
turn 39), crash-watch, `just play scratch`, watch armed. #538 held (no marriage crash since 07:12).

## 2026-11-10 (07:25): rulers on the test laptop (Haiku); the marriage crash found and fixed; tc can't lock

**State 07:25:** the test laptop on main #539, campaign `scratch` playing unattended (turn ~57, from turn 45 at 07:08):
`just play scratch`, crash-watch unit active, `WATCH_BOT=0 just watch scratch` armed from the main machine's session.
Rulers answer in 15-60 s with 0 rejected. tc powers off at 23:59; nothing restarts the loop after the 03:00 boot.

**Rulers on tc (the author's 11-06 pick), measured** on its i7-4810MQ CPU against a real 11.5k-token ruler prompt:
qwen3.5:9b ~11 tok/s reading (≈1000 s a prompt), heretic4b 513 s + 3.4 tok/s, heretic2b 210 s + 8.4 tok/s but
`ruler-eval-fixed` 4/6 answered, 27% legal. `claude:haiku` 6/6, 100% legal, 41 kept, 32 s median: tc's
games/local/scratch.toml now uses it for both brains, the decider and the reader (backup `.bak-20261110`). It
spends the author's Claude usage. heretic2b/4b stay imported in tc's Ollama.

**Done:**
- #537 Ollama seats send `num_ctx` (prompt/3 + 2048, min 8192): the 4096 default cut ruler prompts silently.
- #538 the turn-start marriage crash: 07:11:27 the game offered Michell Merrett a wife and `marryWife` on him in
  the same second crashed it (#535's breadcrumb was the last line; the replay had no offer and passed). Now
  `marry_live` marries nobody while a family offer is pending. **Proven live 07:16:44** (offer for John Giffard,
  "nobody married this turn", game played on; 07:18:44 married George Edwardes). Closes the 11-06 crash lead.
- #539 relaunch_game.sh: the 240 s load wait starts when Steam starts the game; Steam gets 900 s before that
  (`PARLEY_STEAM_START_TIMEOUT`). 07:01 today Steam self-updated after the boot and started the game at ~5 min.
- tc can't lock or sleep: KDE auto-lock/lock-on-resume off, powerdevil DPMS/dim/suspend removed, lid does
  nothing, LightDM autologin for author (`/etc/lightdm/lightdm.conf.d/90-mtw2-autologin.conf`; delete to undo).

**Next:** watch the run (crashes, `offer is open` lines, England's 1-2 orders a turn vs France's 11-18: read
whether England is passive by choice). Before 23:59 `just stop` on tc. Forced-events list below still open.

**For the author:** autologin was your call on 11-05; it's on now under "keep it from locking". Delete the file above
to undo. Haiku rulers spend your Claude usage at about two 12k-token calls a turn.

## 2026-11-06 (13:10): parked on the author's order; rulers move to the test laptop next

the main machine became nearly unusable for the author, and a peer session relayed his order to wrap up at once. Nothing below was
measured or finished after that.

**State:** `just stop` ran on the test laptop about 13:05: game up, paused on turn 45 (main #535), paused.txt holds the stop
text. Tunnel `mtw2-heretic-tunnel` stopped on the main machine. No watch running. GPU mode not touched. The live
acceptance list below is still open.

**Next session, first:** the author's pick 11-06: run the rulers on the test laptop itself, not on the main machine's GPU. Heretic's one
slot starved them: both seats returned no content at 600 s on turns 41, 42 and 43 (0 orders), so that run proved
nothing about ruler play.
- tc already has an `ollama` container (0.35.1, 127.0.0.1:11434, CPU, models in /opt/models/ollama) holding
  `qwen3.5:9b`. No copy from the main machine needed. Check who else uses that container first: mafski-web runs on tc.
- One generate test (80 tokens) beside the running game gave curl no answer in its 170 s. Cause not read: slow
  load, or too slow on this CPU (i7-4810MQ, 8 threads, 15 GB). Read `docker logs ollama` and retry with the
  loop stopped, then beside the game. Too slow means trying the 2B or 4B Heretic GGUF from the main machine
  (/opt/models/gguf, 1.3 and 2.8 GB; tc has no llama-server, Ollama can import a GGUF).
- `claude:haiku` answers on tc today (`claude -p --model haiku` returned ok). It spends the author's Claude usage, so
  it's the fallback and needs saying if used.
- Then edit tc's `games/local/scratch.toml` (seats' decider, gitignored; its reader names agy, not installed
  there), `just seat-smoke`, `just ruler-eval-fixed`, `just play scratch`, `WATCH_BOT=0 just watch scratch`.
  Report measured speed and legal rate. The tunnel stays off unless something needs it.

**Open crash lead (12:29, runs/crashes/2026-11-06-123034):** the log stopped at England's turn 42 start, last lines
`adoption offer: Hugh Stafford for england`, no click on that offer; the replay passed with no offer. Of 9 real
crash reports, 6 stopped within 11 s of a family offer (5 within 4 s). About 125 offers since 11-05, so at most
about 1 in 20. `offered()` reads a batch of event fields, and a batch read crashed turn 67 before; that link is
untested. The #535 breadcrumbs name the step next time.

**Forced events:** 19 forced, 12 route, 3 no_route. Next: fire a crusade at a rival's town to see whether "Join
the Crusade" follows; capture messages 52, 187 and 68 as they fire. Each bench run parks the live run.

## 2026-11-06 (06:45): items 1-3 of the night's list done; marriage declines no longer click

**Next session, in order:**
1. **Forced events, the author's order 11-06 ("we don't want to be at the mercy of the game"):** work through
   `games/forced_events.toml` until every row is forced or has a stated reason it can't be. A row is forced
   only when a bench case sees the GAME react: a helper's own `ok` line passed in 0.1 s and proved nothing, three
   times today. For a new event, throw a probe suite at it and read which game message appears within a second.
   Status and what each open row tried are in that file (19 forced, 3 can't be, 12 open at #533). First up: fire a crusade at a rival's town and see whether "Join the Crusade" follows (seen on turn 16 of a 12-turn awake run), and capture game messages 52, 187 and 68 at the moment they fire: they're unidentified, so excommunication and missions aren't ruled out. Rules learned:
   the quiet world holds off rebellions, offers and missions, so test those with `M.qa.quiet_off()` and `needs`;
   never write campaignDb or setGuildCooldown in a probe (they outlive the bench and reached the live game twice);
   never put a shorter `timeout` around `just qa` (killing it skips the restore; `just qa-restore` recovers).
2. Live acceptance, **started 06:41 on turn 30, still unproven**: the tunnel as the user unit
   `mtw2-heretic-tunnel` on the main machine (a plain `ssh -R` joins the ControlMaster and exits 0), `just play scratch` on
   the test laptop, `WATCH_BOT=0 just watch scratch` (no bot token there; without it the watch exits on a false DOWN).
   Watch for `marriage offer despite pre-marriage` and "declined with Escape" in the turn log. **Don't run
   `just gpu mtw2` without asking the author:** it stops Klarheit's M11/M12 timers and Ollama, and each missed slot
   permanently costs those experiments; mine cost about 06:40-08:28. On shared, Heretic has 1 slot, so rulers
   queue. When the run ends, before 23:59: `just stop`, `systemctl --user stop mtw2-heretic-tunnel`.
3. Fix cause: relaunch_game.sh misses a Steam "Verifying installation" hang (03:00 boot, false crash report
   runs/crashes/2026-11-06-035155). Not started.
4. The author's calls: see "For the author" below.

**Open crash, cause unknown (live 11-06 12:29, runs/crashes/2026-11-06-123034 on the test laptop):** the log stopped at England's turn 42 start, between "trained in York" and "governors england", with `M.marry_live` in that gap and a reopen click 8 s before. Crash-watch relaunched in about a minute; the replay of that turn start went through (12:32:05), also with a reopen click just before, so it isn't deterministic. Neither #519 nor the click is convicted or cleared. #535 adds `turn start <faction>: <step>` and `marrying <name>` lines: the next crash names its step.

**Filed, not fixed:** `just play` prints "turn loop and bot are running" when the bot isn't. The source-read hook
blocks reading out-of-repo source by path from inside a worktree (Read works). agy's edit jobs often time out at
9 minutes on Flash medium, some with no edits at all: run the check on whatever is left.
**Measured 11-06:** 7 accept clicks on marriage scrolls on the bench, 0 crashes (wife 3, suitor 4).

**State 06:45:** the test laptop on main (#525), game up and paused on turn 30 (a copy of the pre-offer run, moved
on by probes), crash-watch active, no loop. The saves holding the open offer are in
`~/mtw2-saves-with-open-offer-20261106` on the test laptop, and `mods/parley/saves/offer_open_t29.sav` reopens that
scroll on any load: `bash scripts/relaunch_game.sh --save offer_open_t29.sav` (a repeatable repro).

**Done (each proven on the bench or live, full suite green):**
- #519 marries single men at the human slot's turn start. Live 05:45: 5 men married at England's turn start.
- #521 frozen_rival_offers_nothing: its first pass was vain (the Aztecs took no turn in the one round seen,
  and `^` matched any line). Rewritten; passed 05:36 and 06:16 with denmark, two whole rounds. The
  ai_diplomacy_offers hold is claimed with its limit written down: the freeze covers a faction's first second.
- #523 a marriage decline presses Escape, not a click (`press_escape`). By hand 05:44-05:48: Escape on the open
  offer, then End Turn reached England's next turn, 3 of 3. Bench 06:04, a suitor scroll through the whole
  loop: pass. An accept still clicks: Escape can't say yes. Not seen: Escape with no scroll opens the game's
  menu; `_finish` looks straight before pressing.
- #524 a pause lifts only for whoever set it. `Orchestrator._answer` lifted any pause, so QA's scripted ruler
  took off `just stop`'s pause. QA relied on that twice by accident: the park now sets the stop pause aside
  (qa.lock `stop_pause`) and the restore puts it back; a turn case lifts the run's own hold itself. Live:
  paused.txt keeps the stop text through a run.
- #522 `just relaunch-game --save X` ignored X (no `[positional-arguments]`).
- #525 a wife offer gets its own wording and skips the suitor score. Not proven: `isMale` on a real wife
  offer's character; if it's missing the old wording stays. The first wife offer live is the test.
- Whole no-click bench on #524: 78 pass, 0 fail, 0 inconclusive, 24 turn cases skipped by design, 16 min
  (runs/qa/2026-11-06-0636-all.md on the test laptop).

**Probed, ruled out:** the offer scroll can't be answered from Lua by name. It isn't among the 4,012 exe names
`M.scan_ui` tries, nor under `strat_ui`, so `execute()` has nothing to act on. (A reply to
EOP-Labs/M2TWEOP-library#91 is public, so it waits for the author.)

**Found, not fixed:** `princess_suitor_offer` isn't held on the bench (games/interrupts.toml). It holds End Turn
about 40 s; Escape answers it now since QA's seat declines. The case's 6 turns may still be inconclusive.

### For the author

1. **Marriage clicks crash sometimes, not always, and #519 was decided on "4 of 4".** See below. #519 still
   removes wife offers, but its stated reason was too strong. Keep it, or restore the offers now that declines
   use Escape (`autoplay.marriage_offers = true`)?
2. **An accepted suitor still needs a click**, the path that may crash (accepted 11-05 19:59 crashed; 20:20 and
   20:41 didn't). Rulers' wishes get carried out, so that stands unless you say otherwise.
3. Escape is keyboard X input, a named last resort under no-clicks-first. It still can't run in a no-click run.

## 2026-11-06 (05:50): open items from the morning session

**"Every marriage click crashes" is wrong; #519 was decided on it, so the author should hear this.** On 11-05
`logs/scratch-turns.log` on the test laptop shows accept clicks at 20:20:14 (Francis Went) and 20:41:20
(Estrelda of_Normandy) with the game playing on, and 11-06 05:35:52 a decline click on the bench survived.
The 19:59:56 crash was on Anthony Despenser, a man's name, so "only the wife scroll crashes" isn't
supported either. Both kinds exist (scroll text): a suitor for a princess, a wife for a man. PR #521's
body overstates this ("the wife offer that crashes").

**Tooling blocks met, not fixed (Refinery's, its session was busy):** surface-write-guard reads a whole
quoted `ssh '...'` as one segment, so a `cp` of a `.sav` beside a `scripts/x.sh` mention is blocked (I ran
the `cp` alone). agy's headless mode denied `test` (`fix_cause`: add `command(test)` to
features/antigravity/permissions.json), and its brief lint rejects `.venv/bin/python`.

## 2026-11-06 (early): marriage-crash fix decided and built (PR #519, unproven); QA still blocked

**Next session, in order:**
1. The live save holds an open marriage offer that comes back on every load, and it blocks `just qa`
   (it waits 600 s for a decision, then refuses). Never click it (4 of 4 clicks crashed). Load an
   earlier autosave, or the bench save, from the menu with no scroll on screen. Then run
   `QA_REAL_GAME=games/local/scratch.toml just qa diplomacy case=frozen_rival_offers_nothing` (#468);
   on a pass, claim the ai_diplomacy_offers hold in games/interrupts.toml.
2. PR #519 (`fix/marriages-in-advance`, not merged): bundle it to the test laptop, `just reload-bridge`,
   `just qa family case=single_men_married_in_advance`. Merge only on a pass and a green full test run.
3. Fix causes: relaunch_game.sh misses a Steam "Verifying installation" hang (03:00 boot: no window,
   restore failed, false crash report runs/crashes/2026-11-06-035155); the popups prompt says "for your
   princess" for a man's marriage offer.
4. Live: `just play scratch` lifts the pause.

**State at 05:10:** the test laptop up, game running and paused (`parley_turns/paused.txt`), crash-watch
on, no loop or QA. Main at #518.

**Decision (the author delegated; risks signed off 11-06 "just-do-it"):** the bridge marries the human
slot's single grown men at its turn start (`M.marry_live` -> `M.marry_singles`, EOP
`characterRecord:marryWife`), so the game has nobody to offer a wife to and no scroll needs a click.
`autoplay.marriage_offers = true` turns offers back on. The ruler's prompt names who was married
(`married-<faction>.txt` in the turn folder). Proven by hand live 11-06 04:10: marryWife married 5
men, no crash; married non-family generals stay non-family. Proven at 04:11: a decline click on an
offer crashed the game even with the man already married, freshly loaded and no End Turn pending, so
the click itself is the cause. Upstream ask: EOP-Labs/M2TWEOP-library#91.

## 2026-11-05 (night): full phase-2 pass in 72 min; holds proven; two new gates

**Next session, in order** (details in the paragraphs below):
1. `just qa diplomacy case=frozen_rival_offers_nothing` (#468). On a pass, claim the ai_diplomacy_offers
   hold in games/interrupts.toml.
2. `just qa family` (#470): should reproduce the marriage-click crash (or come back inconclusive if
   no offer comes). Then the fix the author picks, proven by the same case.
3. Live: `just play scratch` lifts the night's pause (#473); start `just watch scratch` (it now
   wakes on crashes too, #463) and `just crash-watch` if it isn't active.
   State at 22:56: the test laptop paused (`parley_turns/paused.txt` under the game folder), crash-watch
   active, no loop or QA; main at the last of tonight's test-only PRs (#504-#516).
4. The author's calls: the marriage-crash fix; a hotseat campaign for France; the Refinery checker's crash
   on long evidence; popup reader on the test laptop; tunnel vs LAN Heretic.

**Top finding, needs a decision: answering a marriage offer by screen click crashes the game.**
Live 20:00 (run 10, turn 13): England's marriage offer (Anthony Despenser) at 19:59:44, the turn
loop clicked "accept" at 19:59:56, the bridge log stops there, and crash-watch found the crash dialog
at 20:00:49 and relaunched (runs/crashes/2026-11-05-200049 on the test laptop). End Turn was not pending.
The bench showed the same twice (11:57 a decline, 12:15), which is why the bench now marries
England's men so no offer comes (#412) — but a live campaign still gets offers. Options: (a) press
the scroll's buttons through the game's UI from Lua instead of a click (unproven; asked upstream in
EOP-Labs/M2TWEOP-library#91 on 11-05, no reply by 22:30); (b) prevent offers
live too, as the bench does (marries off the rulers' single men: a change to the game); (c) leave the
offer unanswered, if the game lets the turn end. The repro case is written (#470, not yet run):
`just qa family` turns offers back on for one case (M.qa.marriage_offers_on), spawns an unmarried
general and answers the offer; it should fail (crash) until a fix holds, which makes it the bench
proof for whichever option the author picks. An offer within 3 turns is the game's roll (chance case).
Crash-watch recovered this one in under a minute; the turn's decisions were replayed.

**Most important:** the full phase-2 pass (every suite once, 17:26-18:44 on the test laptop) took 72 min,
well inside the 3-hour budget: smoke 2, covert 10, envoys 6, diplomacy 11, field 7, navy 14, towns
5, siege 6, popups 11. 128 of 134 passed; the 3 fails were bench bugs, fixed (#440-#442) and each
passed alone after; 3 inconclusive (the two instant AI-offer cases, which can't pass by design, and
the chance case ai_offer_on_its_turn). Run 10 plays on main (bridge reloaded 19:21, turn 11). The
no-click run on tonight's code (`just qa all kind=instant`, 19:38-19:53) is clean: 77 pass, 0 fail,
0 inconclusive, 21 turn cases skipped by design (runs/qa/2026-11-05-1953-all.md on the test laptop). Again
on the final code (#460, 21:36-21:52): 77/77 (runs/qa/2026-11-05-2152-all.md). End of day: run 10's
turn loop stopped at 20:58 (turn 24), crash-watch on, GPU back to shared (Heretic 1 slot), the
reverse tunnel closed. With no loop, autoplay kept ending turns with no orders (turn 29 by 22:07), so
the campaign is **paused** (`parley_turns/paused.txt` on the test laptop, written by `just stop`). Since
#473 `just stop` always pauses and `just play` lifts that pause by itself; a pause with another
reason (a QA hold, a seat's usage limit) stays.

**Found tonight:** `instant/quiet_world_held`, the bench proof for five interrupt holds, never
existed; `quiet/quiet_world_held` now reads the quiet world back from the game (pass 19:16).
Adoption offers are now held the same way as marriage (EOP familyTree.maxAdoptionAge, live: 30 -> 0
on the bench, back to 30 for the real game); man-of-the-hour offers remain unproven. #443 merged
red because the merge command piped pytest through tail; #444 fixed it and #445 gates that shape.
Lessons reviews (#446, #454) proven live at run 10's turn 20: they started once both rulers had
answered (20:41:19), England's kept 3 lessons in 163 s, France's 3 by 20:47; none timed out. The
second overlapped turn 21's decisions (an answer's thinking cut at 180 s), so #457 now staggers
them, one ruler a turn (not yet seen live: the next review turn is 40).

**France's ruler shares control with France's game AI (open, the author's call).** France is an AI-slot
seat (in run 9 too: "france: game AI frozen" at 16:55). Its game AI is frozen at its turn start, then
unfrozen so the turn can end, and it reshuffles France's armies and captains: run 10 turns 8-11 lost
2-4 French orders a turn as "unknown army" (Captain Henri became Captain Martin on the same tile).
I tried making France a human slot by probe (`isPlayerControlled = 1`, 19:22): the value stuck, but
France's turn 11 then never ended (End Turn pressed 2 s into it; stuck 10 min), so I set it back at
19:35 and the game went on. The bridge is not what failed: it resets autoplay at each human turn
start, and a fake-game test of two human factions ends both turns. The game kept refusing France's
End Turn, so flipping the flag mid-campaign doesn't make a hotseat player; two human slots need a
hotseat campaign started from the menu (clicks, the author's call). Until then AI-slot rulers' army ids go
stale each turn; since #489 and #491 their refusals and role text say why and to use this report's
ids (not yet seen live).

**First ruler-eval baseline on the fixed set (21:00-21:10, Heretic on the main machine, `just ruler-eval-fixed
heretic:think heretic:local`, runs/ruler-eval/20261105-2110.md here):** heretic:think answered 6/6,
87.0% legal orders (47 kept, 7 rejected), median 222 s (its thinking cut at 180 s each time, then the answer written);
heretic:local (no thinking) answered 6/6, 84.2% legal (32 kept, 6 rejected), median 20 s. Without
thinking: about 11x faster, nearly as legal, fewer orders. Gemini Flash low through agy (21:11-21:13,
runs/ruler-eval/20261105-2113.md): 6/6, 100% legal (25 kept, 0 rejected), median 26 s, the fewest
orders. A second run of all three (21:17-21:30, runs/ruler-eval/20261105-2129.md, with #458's order
mix): heretic:think 78.4% legal (9 points below its first run: one run proves little),
heretic:local 83.8%, Gemini 100% again. Kept orders by area: think leans on agents (13 of 40),
local on armies (19 of 31), Gemini spreads them (6 armies, 5 agents, 4 build, 5 recruit, 4 taxes).
Legal is not good: outcome scoring is open.

On a pass of #468, the ai_diplomacy_offers hold reads: held_by freeze=*, proof as ai_attacks_sieges,
bench diplomacy/frozen_rival_offers_nothing.

**Risk profile of the evening (8418247..8330ad6, jcodemunch):** 0.80 "critical", driven by volume
(228 symbols, 73 files, ~50 PRs) and old complexity in lua/parley_bridge.lua (`spawn` 72 paths,
`merge_armies` 49, `merge_units` 34, `bench_marriages_off` 31). Its "94 untested" leads with TOML keys,
not code. A calm-day candidate: split `spawn` and `merge_armies` behind their existing tests.

**Open for the author:** the Refinery's standards_check.py `_evidence_ok` crashes (ENAMETOOLONG) when
`(project / ev).exists()` walks the whole evidence string and its first missing segment is over 255
bytes. One-line fix there: wrap that `exists()` in `try/except OSError` (the Refinery checkout had
someone's uncommitted work tonight, so I didn't touch it). mtw2's tests/test_standards_evidence.py
(#500) catches such evidence meanwhile.

## 2026-11-05 (late): run 9 lost, run 10 started; phase 2 clean

**Most important:** run 9 ended at turn 96 (17:10): Scotland took York, England's last town, and the
game sat on its campaign-over screen. Run 10 started at 17:12 with no clicks: run 9's turns and
databases are archived as `scratch.run9*`, and the game loaded a copy of the bench save
(`mods/parley/saves/scratch_run10_start.sav`, England at turn 5) through `relaunch_game.sh --save`.
In run 10 only England is a human slot (the bench save's); France's ruler still plays, as a seat on
an AI slot (the game's AI frozen on France's turn): both got turn-5 reports and the bridge waits for
both from turn 6 (17:25).

**Phase 2:** every case passes on the bench except the two instant diplomacy offer cases, which can't
pass by design (the AI offers only on its own turn); their turn versions pass (ai_offer_on_its_turn,
two_offers_on_their_turns #434). papal_election_no_vote passes since #430.

**Found live and fixed (#429-#436):** crash-watch was not running 14:41-16:50, so the 16:38 crash sat
until a QA run found it (#433 makes the watch say so); a QA restore on the test laptop failed on the missing
bot token and kept qa.lock (#431); the watch said DOWN during bench runs (#435) and STUCK on a defeat
(#436); refusals for armies that vanished during the AI turns now say why (#429).

**Unexplained:** the 16:38 crash (turn 95), right after England's spy moved into Dijon with French and
Milanese spies inside. The bench case passed and the same orders replayed on the same save ended the
turn normally; the case stays as a guard.

## 2026-11-05 (evening): a live campaign on the merged code; what it showed

**Most important:** from 14:41 the scratch campaign (England and France on Heretic, the rest the
game's AI) has played on the test laptop on main, turn 75 onward, 3-8 min a turn, no crash or stall. Heretic
runs on the main machine (GPU in `just gpu mtw2` mode, ~25 tok/s with both rulers thinking) and the laptop
reaches it through a **reverse ssh tunnel** (`ssh -N -R 127.0.0.1:8090:127.0.0.1:8090 author@<test-laptop-ip>`,
riding the session's ssh connection). Before the night: stop the loop, `just gpu shared`.

**What the live run found (fixed, #419-#424):** the loop answered stale reports from a relaunch before
the real turn (both rulers timed out on turn 75); a loop started over ssh couldn't see the game's popups;
a ruler repeated a refused assassination (no hint what to do); France blamed ambushes for armies that
had simply run out of units. A cross-model review of the day's code (agy, flash-high) found that #419
would have stalled the loop after a reload to an earlier turn; fixed in #424 with two other findings.

**Open (the author):** the test laptop has no popup reader (no agy, claude or tesseract): game messages reach its
rulers unread; installing one needs a login or sudo. Opening Heretic to the LAN instead of the tunnel is
a the main machine network change. Rulers' periodic lessons review times out on Heretic's two busy slots
(harmless, but it competes with the rulers). `papal_election_no_vote`: the bench save sends message 210,
not the notice 202 the case is about; what 210 is needs the game's message table.

## 2026-11-05 (afternoon): phase 2 runs in 51 min; the crash causes found and fixed; merged as #416

**Most important:** the full phase-2 pass (all 97 bench cases, played turns included) ran on
the test laptop in **50 min 33 s** (13:06–13:57): 91 pass, 4 fail, 2 inconclusive. Two of the fails were
fixed and proven one case at a time since (blockade_port, besiege_assault_storms). Everything is in
main through **#416** (929a799; 27 PRs; `just test` 1640 passed).

**Still failing, with the reason:**
- ~~`towns:next_turn_delivers`~~ fixed 14:37 (#418): it builds in London, which stands in 3 turns.
- `popups:papal_election_no_vote`: with England's cardinals dropped, the game sent 201/210/203 but never
  the notice (202) the case is about. The case's premise doesn't happen on this save.
- `diplomacy:ai_offer_accepted`, `second_offer_asked_again`: inconclusive, no offer on screen (as ever).

**What the crashes were (11-05):** (1) stale `popup-*.req` files from earlier runs, kept fresh by the
hold's resume, answered by the turn loop with clicks under a pending End Turn (#411); (2) marriage-offer
scrolls clicked (#412 marries the bench's men so none arise; #410 holds End Turn for any offer);
(3) blockading a rebel port (#414 refuses it, ruler-facing). The Wine log's `\r\n` had made three cases
fail on lines that were there (#407).

**Speed (the author's 6 steps):** a reload 22.5 s → ~15 s (~6 s load + ~8.5 s readiness, a 6 s canary walk);
a played smoke turn ~77 s → ~24 s; a load after a played turn 80–108 s → 25–39 s; whole suites were
11–28 min each this morning, a single case is now 1–5 min (`just qa <suite> case=<name>`).

**For the author:** rebel-port blockades are refused for rulers until proven safe; force-push decision on
public commit 0bf7b81 (old Discord handle); 20 old full-desktop crash screenshots in `runs/crashes/`;
LightDM autologin and Gitea credentials for the test laptop.

**Next:** the towns bench-save gap; the papal no-vote premise; the inconclusive offer cases; then the
ruler track (Jigsaw v0.9.0 is tagged; Parley pins v0.8.0, no rollback past v0.9.0 once moved).

## 2026-11-05: phase 1's last case fixed; docs rewritten for outside help; QA runs over ssh

**Most important:** `marry_foreign_general` is fixed (the princess was disgraced, not married; the
bridge now tells the ruler). **Phase 1 is done:** the full no-click bench on the test laptop came back
clean, 74 pass, 23 skipped (played-turn cases), 0 fail (`runs/qa/2026-11-05-0623-all.md` there,
37 min 40 s). The phase gate is open for phase 2: the played-turn cases, on the test laptop.

**Phase 2 (from 06:42, the test laptop):** played-turn runs found five bugs, each fixed with a test that
fails without it. Merged: #367 (frozen AI let go after 3 s: a played turn ~80 s, was ~5 min). Open,
running together now in the chain (test/phase2-integration 78195fd): #375 (End Turn waits up to
20 s for this turn's agent missions, the covert sabotage race; M.qa.load defers during an AI turn,
the envoys crash: a load 2 s after End Turn), #380 (the QA hold applies on the player's turn only:
it had stopped stuck-turn recovery and Denmark's turn stood 9 min), #381 (a faction whose envoy
parleys at its turn start stays awake that turn: a frozen AI makes no offer), #372
(recruit_merchant builds a market on the bench save; one level per town after review).
Diplomacy's ai_offer_accepted/second_offer_asked_again have never passed (no offer on screen).
The chain (`/tmp/phase2_chain.sh` there; picks up /tmp/integ.bundle before each suite; stops if
qa.lock is left or at 22:00) runs field, navy, popups, siege, towns, instant, envoys, covert,
diplomacy, smoke. Logs `logs/phase2-chain.log`, `logs/phase2-<suite>.log`; `just qa-summary`.

**Privacy (11-05):** scripts/crash_report.py captured the **whole desktop** (`import -window root`)
before every crash-watch relaunch. Fixed in #376 (game windows only) with
tests/test_no_desktop_capture.py forbidding any whole-screen capture. **20 old reports in
runs/crashes/ on the main machine hold full-desktop screen.png files** (gitignored, never published; not opened);
deleting them is the author's call. Caveat: X11 `import -window <game>` can still include a window lying
on top of the game window.

**Merged 11-05 later:** #365 `just work-until HH:MM` (a Stop hook holds a standing order; the author
set 23:00), #366/#370 STANDARDS fixes, #368 parallel-seats test by barrier, #369 bridge log cap
(20 MB, rotated before a relaunch). Posted EOP-Labs/M2TWEOP-library#91 (papal vote and family
offers from Lua). agy: only Gemini Argon is out of quota (till 11-06 17:41 UTC); Flash works.
Then #374 `just qa-summary` (written by agy, checked here), #376 privacy fix, #377 a QA crash writes
a crash report before the relaunch. agy is building `just ruler-eval` (STANDARDS ruler-eval-harness)
in <scratch dir> (branch feat/ruler-eval).

**Merged earlier 11-05, stacked:** #361 (marry fix) → #362 (README, CONTRIBUTING, guide;
`EOP_BUILD=master just install-eop`) → #364 (QA over ssh: a held game isn't hung, the run's own
probe passes its lock, the run borrows the desktop's display). Then refresh the public GitHub copy
(`python3 _review/scrub_public.py main <dir>`, gitignored because it lists what it hides; one
snapshot commit on c6e8dca, to GitHub and Gitea mtw2-public).

**the test laptop:** powers off 23:59, back 03:00, then waits at the LightDM login screen (nobody logged
in: no game). `PARLEY_POWER_OFF=23:59` in its parley.conf (#359). The author said it's ours until 23:00
today. It can't fetch from Gitea (no credentials): ship branches as git bundles. A stray
`parley_turns/qa.lock.test-probe` is there (harmless; the guard wouldn't let me move it).

**Drafts for the author, not posted:** `_review/2026-11-05-eop-discord-question-draft.md` (ask EOP's
Discord how to press the papal vote and family offers from Lua) and
`_review/2026-11-05-eop-issue-89-comment-draft.md` (issue #89: mercenaries now by direct write,
agent costs from a fixed table).

## 2026-11-04 night: the test laptop runs the bench; phase 1 down to marry_foreign_general

**Most important (then):** phase 1 had one open case, `marry_foreign_general` (fixed 11-05).

**the test laptop (<test-laptop-ip>) is the test machine now.** The game runs there with no clicks (Proton 10,
`PROTON_USE_WINED3D=1 WINEDLLOVERRIDES=d3d9=n,b` so EOP's d3d9 hook loads first), and the full
no-click bench ran in 38 min (71 pass, the same as the main machine). Every step is in
`_review/2026-11-04-the test laptop-setup-log.md`. Quirks:
- One Steam account runs the game on one machine at a time: launching on the main machine while the test laptop
  plays does nothing (Steam takes the URL and starts no game).
- A locked desktop stalls the game behind the lock screen; `relaunch-game` now refuses at once on
  a locked session (#355). the test laptop was **left unlocked with auto-lock off for the night**.
- It powers off at 23:59 local and back on at 03:00 every night (seen 11-03 to 11-05; set
  outside the user crontab). `PARLEY_POWER_OFF=23:59` in its parley.conf makes a QA run that
  would cross it refuse to start. After 03:00 it waits at the LightDM login screen: nobody is
  logged in, so no game can start until someone logs in (or LightDM autologin is set: The author's call).
  `relaunch-game` now says so at once; it also starts Steam from ssh (borrows the desktop's DISPLAY,
  reads PARLEY_STEAM_URL from environment.d). A cut-off test left a qa.lock there (11-05 03:47,
  real campaign not running before): `just qa-restore --real games/local/scratch.toml` after login.
- Its Steam asks which launch option to use; `~/.config/environment.d/parley.conf` sets
  `PARLEY_STEAM_URL=steam://launch/4700/option0` (#353).
- Its game is held (`parley_turns/paused.txt`): the copied bridge.txt has autoplay on and no rulers
  run there. Its checkout is on main (d69668b, 11-05). **Open:** it has no Gitea credentials, so
  `git fetch` fails ("could not read Username") and code goes over as git bundles. Fix: a read-only
  Gitea token (or deploy key) for it; the author's call, since it's a new credential on that machine.

**`marry_foreign_general` fixed (11-05):** the princess wasn't married, she was disgraced. A probe
listing every copy of both characters showed Cecilia's record going `alive=false, spouse=nil` 10 s
after the order (with popup message 160), the suitor still Polish and unmarried, in both 11-05
probes; she vanished in all 4 runs since 11-04 (the bench save replays the same roll). Poland's AI
wasn't frozen in England's turn (freeze=0), so a frozen suitor faction isn't the cause. The game has that outcome: event_titles.txt
`{mission_marriage_fail_and_removed}Princess Disgraced!`, and it fires no mission event. The
bridge now remembers each marry order and reports a princess found dead with no mission line when
the news is read; the case reads `M.qa.news`. Passed live on the test laptop. EOP's `character:marry`
(EOP-Labs/M2TWEOP-library `actionsStrat.cpp:204-219`) only issues the game's own action (type 34).

**Merged tonight:** #353 (PARLEY_STEAM_URL), #354 (the gate ignores heredoc text), #355 (locked
desktop), #356 (`repair_queued`: a repair is paid at once with at most one item ahead of it; queue 2
pays nothing at queue time; proven on the test laptop's towns suite), #357 (`crossing_in_one_turn`: the
fleet must end beside the far shore; it stopped at 118,146 with 27 of 80 moves left because
`M.qa.sea` picked an unreachable tile; proven on the test laptop's navy suite).

**`marry_foreign_general`:** with England's own princess and a valid suitor on the bench, the order
is taken, the princess leaves the map within seconds, no mission event comes, and 25 s later the
suitor (Boleslaw Herman, Poland) is still Polish and unmarried. A rejected proposal looks
different: the event fires and the princess stays (Ysabel, France, live). Next: one played turn
after the proposal (phase 2), or EOP 3.3.1's own marry code.

**Needs the author:** re-lock the test laptop; the main machine's Steam showed an on-screen notice on a launch tonight
(likely Steam Cloud, after the game ran under the same account on the test laptop); start the Discord
bot if the queued updates should post.

## 2026-11-04: repair_queued passes; the phase gate had a hole; Jigsaw is public

**Most important:** phase 1 still has two open cases (`marry_foreign_general` half found,
`crossing_in_one_turn` untouched), and the gate stays shut until a clean
`just qa all kind=instant`. Answer "now what?" with the next step; start only on the author's go.

**State at session end:** the game is running on scratch at turn 74 with the loop stopped
(`just play scratch` to resume). Live probes changed that campaign: Michault and Karl were
moved, Lorin de Calais spawned, and a spawned princess vanished. Saves are expendable. The main
checkout is on `fix/qa-open-cases` (merged); switch to main before new work. The old
`.claude/worktrees/session-end` (11-01, merged #347) is still there.

**Done:** `repair_queued` passes on the bench (no-click, instant). The 11-01 cache fix made the
repair show, and the case's charge rule was wrong: a repair is paid in full when queued, even
behind others (London 13473 -> 13073 with the queue at 1). The fake game in
`tests/test_qa_towns_lua.py` now charges a repair the same way.

**Fixed:**
- The forced-events gate (`.claude/preflight.toml`) missed `timeout 590 just qa ...`, so a run
  played smoke's turn cases while phase 1 was open (`tests/test_preflight_match.py`).
- The park took the turn from a stale heartbeat after a relaunch (bench turn 6, real 74), and
  the restore then refused. It now uses the bridge log's newest campaign load when that's newer.

**Found, open (phase 2, click/turn):** smoke `teleport` crashed the game right after
`spawn_agent`'s played turn (11-04 10:12:58, `runs/qa/2026-11-04-1012-towns.md`).

**Elsewhere:** PRODUCT.md (#348); Jigsaw public v0.1.0, pinned by tag (CLAUDE.md); the Gitea
container's DNS had died, so every GitHub mirror failed (gitea-infra #18).

**`marry_foreign_general` (still fails, cause half found):**
- 11 fails had one setup cause: spawned characters can't marry. A spawned general has
  `isFamily` false, and the game ran no proposal to him; a spawned princess vanished at the
  order. Live on the real campaign, a real princess (Ysabel, France) and a real bachelor (Karl,
  HRE) gave `marriage proposal: not successful (chance was 20%)` 5 s after the order.
- The case now uses real family members (`M.qa.wooer/princess/bachelor`). The suitor is
  unmarried, of age, of the wooer's religion, at peace, leading a field army, and not his
  faction's leader or heir. On the bench a heir (Affonso) took no proposal, and a governor
  moved out of town wasn't in sight.
- `M.on_agent_mission` no longer drops a report when one field can't be read, and logs if
  it can't read one at all.
- **Open:** on the bench, a valid proposal (Constance of France to Boleslaw Herman, Poland)
  makes the princess leave the map with no mission event, no message, and the suitor still
  unmarried 20 s on. Every marriage event logged so far is a failure. Next: check the suitor
  and the princess after one played turn (phase 2), and read EOP 3.3.1's own `marry` (the
  indexed EOP source is master, and its index is partial).

**Next:** `crossing_in_one_turn`; then `just qa all kind=instant`; then the marriage outcome
above.

## 2026-11-01 (06:00): order fixed by a gate; quiet world built, not bench-proven; phase-1 rerun running

**Most important:** no-click first. `just qa` now refuses turn runs while the newest
`runs/qa/*-all.md` has a fail or inconclusive (#346). This session started on the quiet world
(turn work) over phase 1's open cases until the author asked why; Uncle J's audit traced it to the
04:45 handoff's order and to no-clicks-first living only in memory. Both are now in STANDARDS.md
(`phase-order`, `no-clicks-first`) and checked by the gate.

**Running:** a full no-click baseline, `PARLEY_NO_X_INPUT=1 just qa all kind=instant --real
games/local/scratch.toml`, started 05:27 on main as of #345 (log in this session's scratchpad,
report lands in `runs/qa/2026-11-01-*-all.md`). It parks and restores scratch.

**Merged:** #342 (young Pope, with the Uncle J session's agy job), #343 (journal), #344 (leader/heir;
uv.lock fix), #345 (towns: turmoil, rebel chance, plague; event splits), #346 (the gate, bench proof
for holds, STANDARDS). Live writes checked by hand on scratch only (Pope 55->30, leaders 54/49->45,
11 towns calmed). **No hold counts until `instant/quiet_world_held` passes on the bench.**

**Unmerged:** `.claude/worktrees/quiet-case` (branch `feat/quiet-bench-case`): the
`quiet_world_held` instant case appended to games/qa/instant.toml; 2 tests fail there (one is
`test_the_instant_suite_loads_and_needs_only_the_garrison_town`, likely a case-list assertion;
the other not read). `feat/far-board` still needs its navy bench proof.

**Next (in order):**
1. Read the new phase-1 report. Fix each fail/inconclusive with a bench case that fails first:
   `marry_foreign_general` (order ok, no mission), `crossing_in_one_turn` (fleet a tile short,
   118,146 vs 118,145), `repair_queued` (nothing repairable after 50% damage).
2. Finish and merge `quiet_world_held`, then rerun it so the four holds count.
3. Prove `feat/far-board` on the navy suite (run from that branch's bridge).
4. Only then: a no-mouse decision press through EOP (marriage/AI offers/papal vote, item 4), then
   the remaining interrupt events.

**Quirks:** agy quota out ~127 h from 04:52 (resets ~11-06). `just install-bridge` copies; the game
needs `just reload-bridge`. Never `git commit -a` in the main checkout: uv.lock drifts there.
The Uncle J session and its agy job edited this checkout at 04:48: agy edit jobs go in worktrees.

## 2026-11-01 (04:45): phase 1 at 71/1/2; screens-off root cause; far board unmerged

**Running:** scratch campaign turn ~51 (loop, bot, crash-watch, screen-awake). Watch restarted at wrap-up.

**Phase 1 (no-click) bench, 04:42:** 71 pass, 1 fail (`marry_foreign_general`), 2 inconclusive
(`crossing_in_one_turn` setup expects the fleet a tile off; `repair_queued` found nothing damaged),
23 skipped (click phase). Was 59/11/5/22 at 10-31 15:18. Report: `runs/qa/2026-11-01-0442-all.md`.

**Merged this session (#325-#339):** tiles armies can't stand on skipped (#326); tile visibility >= 3
counts as seen (#327; rulers' sight lists were dropping enemies beside own towns); a load clears agent
order records (#328); park waits for an on-screen decision + Heretic decision time 480 s / bridge
DECIDE_WAIT 540 (#329); reload-bridge waits for the reload (#330); board by whole-army split, armies
aboard named by their unit's general (#331); land by whole-army split (#332, the author's question: the
landed army was the general alone); screen-awake inhibit (#333); crash-watch and the watch probe the
game before calling silence a crash/stall (#334/#335); NE Catapult, build cost on start, storming to
phase 2 (#336); **governors were never switched off** (0/1 written to EOP booleans; #337); watch
STUCK reads the newest stuck line, stale after 3 min (#338/#339). scratch.toml (local): seat_timeout
600, autoplay wait 720.

**Screens off = game crawls** (bench load 66.5 s vs 6.5 s, A/B 19:11/19:14; focus is NOT the cause,
A/B 18:5x). agy's research (`_review/headless-display.md`): DXVK vsync waits on vblanks the NVIDIA
driver stops with DPMS off. The game does use DXVK's d3d9 (checked). **Untested fix:** `dxvk.conf`
with `d3d9.presentInterval = 0` and `d3d9.maxFrameRate = 60` (game dir and mods/parley), relaunch,
`xset dpms force off`, one-case bench. The author: test it when he steps away. screen-awake stays until then.

**Papal election stalled turn 50 for hours** (minimized; bridge hands-off). The tick vote found the
vote scroll live (03:47) and voted, but the xdotool click didn't land (the author had the mouse); the author voted
by hand; results ran clean. No-click papal vote = its own session (forced-election bench case, then a
gameSTDUI press). My blocking AskUserQuestion also stopped the 20-min cron for hours: while the author is
away, never block on a question; post it to Discord instead.

**Unmerged, needs a bench proof:** `feat/far-board` (78ea8ee, pushed): a board order to a far fleet
walks to a land tile beside it and a pending board embarks it by split when adjacent (the author's choice).
Written by agy, reviewed; garrison-key bug fixed in review; 1520 tests pass. Prove with the navy suite
plus the captain round trip (`$scratchpad/captain.sh`, a captain-led army: does its name hold across
board/land? The author asked).

**Next (in order):** 1. the quiet world for turn cases (young Pope via EOP character age after each
bench load first, then the rest of `games/interrupts.toml`; the #340 gate blocks turn runs until then);
2. prove and merge far-board; 3. DXVK screens-off test; 4. no-click papal vote; 5. marry_foreign_general
(game runs no mission; religion and age ruled out); 6. phase 2 (click) run.

## 2026-11-01: turn-playing QA runs are gated on interrupting events

A new preflight gate (`.claude/preflight.toml`, enforced by the Refinery's global hook) refuses any
`just qa` run with a turn case until every event in `games/interrupts.toml` is held (with code proof)
or ruled out. **Only AI attacks are held today, so turn-playing runs are blocked.** `kind=instant` runs
still go. Next: build the quiet world the 11-01 session planned (young Pope after each bench load,
then the rest of the list), record each in `games/interrupts.toml`, and the gate opens by itself.
Never delete an event to get a run through.

## 2026-10-31 (late): QA bench hardened (#320-#324); phase-1 rerun is next

**Running:** the scratch campaign, turn ~7. It advances unattended because run9's loop is paused. No
watchers or QA runs are left behind.

**Merged #320-#324:**
- #320: the restore reads the real turn from the log.
- #321: EOP "Cannot create M2TWEOP save file" box. Missing-save loads are refused, `scripts/eop_error_box.sh`
  detects the box, and crash-watch closes it and relaunches. The bench case `load_missing_save_refused` passes.
- #322: the hold is kept until the real campaign reloads; the relaunch holds under a qa.lock; there's a
  canary ready gate after each bench load; the report has a reload column and flags slow loads.
- #323: the park holds first; the bridge must answer before the first load (180 s); any smoke pass
  records qa.last_smoke.
- #324: STANDARDS.md parses.

**Root cause of "moves don't happen":** a busy game. While AI turns play, loads take 60-75 s and
`moveToTile` gets ignored. On an idle game every move case passes.

**Next:**
1. Gate test, never run live: `PARLEY_NO_X_INPUT=1 just qa field kind=instant case=move_army case=spawn_army --real games/local/scratch.toml`.
   Then the full phase 1: `just stop; PARLEY_NO_X_INPUT=1 just qa all kind=instant --real games/local/scratch.toml`.
2. Fix `garrison_general_leaves` (William won't leave London) and `withdraw` (spawn lands a tile off).
3. The author's call: rank ruler-budget (#8) and wishes-carried-out (#15) higher in STANDARDS.
4. Phase 2 click work overnight.

## 2026-10-31 (00:40): papal crash cause found; generals leave towns by split; fix rounds paused

**Running:** run8 turn ~62. England is down to London + Nottingham (lost Paris, Caen before T40, York
T55-60), treasury ~0, income +1.4k: ruler quality is a question for the author, separate from tonight's
bugs. Loop, bot, crash-watch unit, `WAKE_ON_AUDIT=1 just watch scratch`, a papal-election watcher.
New fix rounds paused at 00:40 to save Claude usage (agy is out until ~11-06); wakes still get fixed.

**Papal crash: cause found.** With our Lua doing nothing in `onScrollOpened` for papal scrolls
(#289 `papal_hands_off`), 4/4 QA field runs played the crash turns 59-67 clean (3 of 4 crashed with it
off). #290 makes hands-off the default (run8 too, live 23:41) and finds the ruler's vote from the
tick (one guarded `getUiElement("papal_election_scroll")` every 2 s after the death notice), never in
the callback. **Unproven:** a live vote found from the tick (watcher running). #275/#280/#283/#288
stay (harmless guards).

**Merged since 22:40 (#288-#293):** End Turn waits for offers (#288); papal hands-off switch (#289)
and default + tick vote (#290); QA home pick, turn wait 240 s > hold, no false LOST? after QA (#291);
generals inside a town leave by `factionStruct:splitArmy` (#292), with the unit from the stack's
`getUnit(i)` (#293). **Live:** the split works but takes effect a moment later (the immediate
"still in London" log line is misleading; next-turn check is right; QA move_army from London passed).

**Open:** 1. prove the tick vote on a live election; 2. QA field flakiness: spawns off by a tile when
occupied, spawned armies absorbed into Nottingham's garrison during AI turns (governors? retreats?
unknown), a stuck QA turn 80 popup; 3. `garrison_general_leaves` not yet reached on the bench with
#293; 4. France ~60% order rejections; 5. 17 MB bridge log rotation; 6. older items below.

## 2026-10-30 (22:40): papal crash narrowed to a click race; crash-watch is a unit; QA mostly green

**Running:** run8 turn ~55. Loop, bot, campaign watch; crash-watch is now the systemd user unit
`parley-crash-watch` (`just crash-watch`, `just crash-watch-stop`; #282). Never start it from a
background job. QA: `just qa covert` 6/7, `just qa field` 6+ of 13 (last run crashed mid-way).

**Merged since 20:10 (#279-#286):** loyal spawned generals + scene setup (#279); papal notice left
alone 15 s (#280); crash dialog caught at once, post-QA relaunch reloads run8's kept save (#281);
crash-watch unit (#282); papal window: loop presses nothing during an election (#283); marriage
offers no longer answered by other prompts, End Turn waits for the spy report (#284); QA funds and
assassin placement (#285); **sight: foreign armies with no `leader` (forts, some field stacks) are
now seen** (#286; run8's Captain Nicholas vanished from England's reports after T49 because of this).

**Papal crash, current understanding (NOT fixed):** #275 (no bridge UI calls) refuted 20:48; #283's
papal window helps notice-led elections but a **results-only** election (no notice) still crashes
when the turn loop clicks a decision in the same second: 20:48:34 (marriage decline) and 22:28:59.2
(marriage decline) → crash 5 s later; 20:56:36 same pattern survived once. Next: answer AI offers
during AI turns without screen clicks (EOP diplomacy/decision API? script command?), or hold decision
clicks after "ending turn" until the player's turn starts if the game tolerates waiting offers. The
QA field run reaches turn 59/62 (a marriage + results-only election) to reproduce it.

**Open:** 1. the papal click race above; 2. confirm #286 live (bridge log probes `sight: ... no
general` / `tile visibility`); 3. QA field cases after the papal crash point; 4. France's ~60% order
rejections; 5. 17 MB bridge log rotation; 6. older Next list below.

## 2026-10-30 (20:10): QA bench (`just qa`) built and proven live; run8; agy out for the week

**Running:** run8 (started 15:27 after run7's England was conquered at T108), turn ~37, England 5
towns (took York + Paris). Loop, bot, crash-watch, `WAKE_ON_AUDIT=1 just watch scratch`.
The author is away; he gets `# 🛠️ MTW2 UPDATE` posts in the Discord chronicle at milestones and hourly
(memory periodic-updates).

**The QA bench** (spec `docs/superpowers/specs/2026-10-30-test-bench-design.md`, plan
`docs/superpowers/plans/2026-10-30-qa-bench.md`): `just qa <smoke|covert|field>` keeps the real
save, stops the real loop/bot/crash-watch, plays scripted cases in the real game on a copy under
`game_id qa-<suite>`, writes `runs/qa/<stamp>-<suite>.md`, then loads the kept save back and restarts
everything. Stop `just watch` before a run, restart it after. Gate: one real autosave between runs
(use the scratchpad-style wait: newest `mods/parley/saves/Autosave*.sav` newer than
`parley_turns/qa.last_restore`). `just qa-restore` finishes a restore by hand (lock-gated).
**Live (the author agreed 10-30):** the live campaign is the acceptance step; fixes are first proven by QA.

**Proven live by QA today:** #255 spy report closed; sabotage; #263 across-the-sea refusals; #267
no-moves guard; withdraw; merge_armies; spawn/teleport/skill/money helpers; park/restore (many
times); #273 hang recovery; #275 papal election ran clean once (19:47) with no UI call.

**Open (next):** 1. PR from the field round-2 agent (move_army stopped a tile short; march_on siege
case needs a hostile target; march_on_across_sea army vanished; garrison case needs a home town;
covert aborted waiting for its turn) — review, merge, rerun `just qa covert` and `just qa field`;
2. a few more clean papal elections before calling #275 proven; 3. France's ~60% order rejections
(disband count 0, unaffordable orders, agents a town can't train); 4. bridge log is 17 MB and never
rotates; 5. the unexplained run8 T18 Paris move (field case `garrison_general_leaves` is meant to
reproduce it); 6. then the older Next list below (SAGA live A/B, Heretic slots).

**Delegation:** agy's weekly quota ran out at 17:25 (resets ~11-06); Claude agents do code work.
agy can now read the game install (Uncle J). Close the Chrome tab that slowed Heretic (still frozen).

## 2026-10-30 (14:50): back from the outage; seats were dead 83-96; Heretic slow from a Chrome tab

**Running:** run7, loop + bot, crash-watch, `WAKE_ON_AUDIT=1 just watch scratch` (now with SEATS).
England is down to London (lost York at report turn 87; treasury -18.8k, -1.9k/turn); France 8 towns,
+4.7k/turn. England played most of 83-96 without a ruler (see below). Restart only when England is lost.

**What went wrong:** from 12:36 every England and France seat timed out (420 s, 0 orders), 50 in a
row; the watch couldn't see it (#258 adds SEATS). Cause: Heretic decoded at ~6 tok/s per slot instead
of ~25. Not the GPU fit, not thread count (4/5/6 threads tested, no change; compose left as it was),
not CPU priority or pinning. **A Chrome renderer (pid 79828, a background tab spinning at 100% since
boot) was the cause**: SIGSTOP on it → 25 tok/s at once, SIGCONT → 6-8 again. Likely GPU work (WebGL/
video) competing with Heretic. **It's left frozen (SIGSTOP)**; `kill -CONT 79828` thaws it; closing
that tab is the real fix (the author: which tab?). Check for such a tab after every reboot: a session restore
reopens it.

**Merged today after the outage:** #254 relaunch (live-proven at 12:14), #255 spy report scroll (not
yet seen live; a one-shot grep waits), #256/#257 wake procedure (agy first), #258 SEATS watch check.
The author, 10-30: fix as you go, also while he's away; restart Heretic freely during testing.

**Next:** 1. confirm seats return orders now; 2. close the Chrome tab for good (the author); 3. the 12:05
crash: cause unknown (after AI agent missions; #255's field read is a suspect only if it repeats);
4. SAGA live A/B (below).

## 2026-10-30 (10:20): stopped for a planned power outage; how to resume

**Stopped cleanly before the outage** (the author, 10:15): run7 at game turn ~71; the newest save is the
game's per-turn `Autosave.sav`. England holds London and York (lost Caen T58 to Portugal, Nottingham
T60 to Scotland while holding 11k florins: #247 is the answer); France 8 towns (took Bruges T70).

**To resume after power returns** (Claude does all of this when the author says "continue"):
1. GPU: Heretic must be up: `curl -s 127.0.0.1:8090/health` returns ok. If not, the GPU came back
   in shared mode: `just gpu mtw2` in the author's tooling repo, wait for health ok.
2. `just play scratch` (loop + Discord bot) **before** the game, then `just relaunch-game`: it starts
   the game through Steam, presses the M2EX launcher's **Run mod** (retries, #248) and the menu's
   **Continue Campaign** (the newest save). If it fails, do it by hand: launcher window "M2TWEOP",
   Run mod at screen (956,534); game window "Medieval 2" at (4,30) 1600x900, Continue Campaign at
   (376,361). Confirm with "bridge reloaded"/orders lines in parley_turns/parley_bridge.log.
3. `just crash-watch` (relaunches after a crash; since 10-30 it starts the user unit
   `parley-crash-watch` and returns at once, so it needs no background job), and
   `just watch scratch` with run_in_background in Claude; restart the watch after every wake.
4. Ping the author only for screen-only help: Discord chronicle via the outbox (memory: ping-author-on-discord).

**SAGA verdict (both rounds, `_review/2026-10-30-saga-experiment.md`):** no tool variant beats the
full prompt (tools on a slim prompt: passive; hybrid: no model used a tool, Haiku ties; planner + 4
controllers: more orders, loses 6-7 of 8 on quality, ~2x cost). Don't wire into live play. Untested:
a planner whose goals persist over several live turns; Heretic in saga mode.
Config is local: `games/local/scratch.toml` (both `heretic:think`, `steward = true`,
`seat_timeout` 420, autoplay `wait` 540).

**Merged since the section below (#240-#250):** per-faction strategy notes + England's (#240-241);
enemy army composition, sight by EOP `getTileVisibility` (confirmed live, #242); revolt risk per town
+ siege/assault checks as advice (#243); order cap scales with the realm, papal crash trace,
outlive status (#244); uv.lock restored + `tests/test_uv_lock.py` (#245); `hire_mercenary` by the
game's rules (#246, not yet seen live); THREATS gives the gap in men, costs, arrival (#247);
relaunch retries Run mod (#248); rulers start as soon as their own report lands (#249: France's
orders were late behind England's); a heartbeat line while waiting for rulers (#250).

**Live results:** siege equipment call ran without a crash (France kept the siege of Bruges T70 and
took it; queued count not seen). Papal results crash #6 at 08:41 (T61): the trace shows the bridge
finished its calls (`getUiElement returned, found=false`) and the game died after: a game-side crash
while that scroll is up; the same turn passed on reload.

**SAGA experiment** (`feat/saga-tools`, not merged; `_review/2026-10-30-saga-experiment.md`):
round 1, tools on a slim prompt, lost for every model (models don't pull; passive play). Round 2
(hybrid prompt; SAGA's planner + per-domain controllers) cut short by the outage: see the review
file for what finished.

**Next:** 1. SAGA fair test (the author: give it a real chance; memory saga-fair-chance): a LIVE A/B over 20-40 turns, one seat in saga mode with a persistent plan carried across turns (replan every ~6 turns or on an emergency), Sonnet as brain (Heretic too when a slot is free), the other seat single-shot; compare towns, income, refusals; also try native tool calling; 2. popup decider
and chat share Heretic's 2 slots with two thinking rulers (timeouts): a 3rd slot or another brain;
3. watch #246 hire_mercenary and the revolt flags live; 4. the 30 EOP gaps and legal actions
(`_review/2026-10-30-legal-actions.md`: split_army, denounce/acquire, crusade join, demolish);
5. papal crash: game-side, consider pressing nothing and waiting longer on that scroll.

## 2026-10-30 (08:10): strategy round: economy, fleets, sieges, militia, lessons, EOP map

**Running:** run7 at turn ~55, both rulers `heretic:think` + `steward = true`, `seat_timeout` 420.
England: 3 towns, income 3,488/turn (was 806 at T47), every garrison filled, at war with Scotland,
plan "besiege and assault York by T55". France: 7 towns, 14 armies, income 2,618, at peace.

**The author's strategy rulings (10-30):** no rigid region pace (behind early, then a financial
powerhouse steamrolls); debt to take a town is fine, don't shed troops when negative; scout ships +
one big fleet sinks troop fleets; militia = garrison duty (order cheaply, defend sieges); garrison
units by order + cheap upkeep + defence; both rulers think (rulers on many machines later).

**Merged #230-#238:** debt is a tool (#230); enemy fleets and their cargo + THREATS line (#231);
lessons review sees OUTCOMES (#232); goal block: economy, phase, stuck-plan by target town (#233);
primer playbook from game files (free slots by wall level, militia; #234); besieging armies queue
siege equipment via EOP's siegeSettlement(town,false) "maintain" path (#235, **not yet seen live**:
a background check waits for "keeps the siege"); steward garrison units from `parley/data/units.json`
(free militia first, else best defence per upkeep, upkeep <= 1.5x cheapest; #236); primer on
siege engines and multi-stack attacks (#237); `docs/EOP-COVERAGE.md` + `just eop-coverage` (#238:
3,053 EOP members, ~239 campaign-relevant used; 30 highest-value gaps listed up top).

**Lessons to veto (the author's call, `just lessons-veto <id>`):** 41a7d878, da4def8d, 19d0035a,
9a6a978c, 05462f8d, 4ef256cb, c6c96c95, d2673dc3, e3b1e16b (contradicted by run5/run6 outcomes).

**In review:** the author's `~/Downloads/england-m2tw-guide.md` (agent ->
`_review/2026-10-30-england-guide-review.md`); proposes a per-faction strategy note.

**Next:** 1. live-check siege equipment (siege_queue > 0) and the T60 lessons review; 2. EOP gaps
worth building first: enemy army composition, which own armies can reinforce a fight, reachable
tiles (`getMovementExtents`); 3. the 40-order cap; 4. after 18:10 UTC: Gemini rechecks the
strategy/naval research; 5. diplomacy screen left open; papal results crash; slow seat blocks.

## 2026-10-30 (07:00): helping the small ruler; Heretic thinks now

**Running:** `scratch` run7 (turn ~46), loop, bot, crash-watch, `just watch scratch` (background).
England and France now on **`heretic:think`** with **`steward = true`** (the author, 10-30: thinking on for every Heretic ruler;
benched 170-214 s alone vs ~37 s; live with both thinking, France 208-233 s and England timed out
at 300 on turn 45, so `seat_timeout` 420 and autoplay `wait` 480 since 07:05; seat errors now read
"heretic failed", not "openai failed" (#228: Heretic runs through the OpenAI-compatible seat)).
The game file is local: `games/local/scratch.toml`. Restart rules as in the section below.

**The author's rule, widened 10-30:** work may be offloaded (steward, checker) **so long as the LLM's
wishes are always carried out**: fill gaps, warn, catch orders that can't work; never override or
block an order the game would accept; tell the ruler what was done.

**Reviews (local, `_review/`):** `2026-10-30-run6-england-loss.md` (57% of Heretic's orders refused
vs 4% for Sonnet; ~90 turns marching at towns across the sea with no fleet; garrisons stripped;
London rebelled at T186 after a tax rise) and `2026-10-30-mtw2-strategy.md` (draft, thin sources:
have Gemini check it against TWC after 18:10 UTC).

**Merged this morning:** #218 compaction hook (`scripts/compact_context.sh`, NOTIFY-CLAUDE §6;
fired correctly on its first compaction), #219 Discord lines name the ruler's model, #220 uv.lock
restored, #221 refused orders at the top of the prompt, #222 besiege/agent walks across the sea
refused (bridge reloaded live at T44; check `by_land` in England's next state.json).

**Then merged and live:** #224 (reload releases a frozen turn; bridge reloaded at T46), #225
steward garrison backfill, #226 leaner prompt + THREATS + primer rules of thumb. Loop restarted on
them at ~06:55. Reload the bridge only during England's turn (no frozen faction) until #224 has been
in a reload once.

**Bugs seen, not fixed:** the diplomacy screen stays open after accepting an AI offer (05:15, run7;
cleared by focusing the game and pressing Escape); England strips garrisons (the steward is the fix).

**Next:** 1. watch the next ~10 turns: refusal rate (was 23% run7, 57% run6), steward notes,
thinking-turn times vs the 300 s cut-off, THREATS lines vs the game; 1b. the 40-order cap
(`validate.py` MAX_ORDERS) counts refused orders and will cut a big realm's turn (and the steward's
recruits first): scale it with settlements + armies before any realm passes ~15 settlements; 2. after 18:10 UTC: Gemini checks the strategy draft, England on Gemini to
compare; 3. diplomacy screen left open; 4. papal election results crash; 5. one slow seat blocks
the other in the loop; 6. draft the narrow M2TWEOP ask (the author to approve before posting).

## 2026-10-30 (05:20): new campaign (run7) running; the watch is in the repo

**Running, unattended:** `scratch` run7 (started 10-30 ~05:00, turn ~1), loop, bot, crash-watch.
England and France on `heretic:local`. **No watch runs once this session ends**: the next session
starts it with `just watch scratch` in the background (run_in_background) and handles what it prints.
Restart the campaign whenever England is lost (the author: keep going): stop loop/bot/game, move
`parley_turns/scratch` and `scratch.db` to `.runN`, `just play scratch` **before** launching the game,
then the M2EX launcher Run mod -> Single Player -> Grand Campaign -> START.

**Runs overnight:** run5 England on Sonnet grew to 5 settlements, then lost under Heretic by turn 166;
run6 (Heretic) conquered on turn 189 and not restarted, because the old watch missed it (fixed, #215).
Archives: `parley_turns/scratch.run5*`, `scratch.run6*`. run7 has stray empty `turn-0191..0193`
folders (no state.json; harmless to the watch, which uses the newest England report).

**Merged since the last section:** #208-#215 (see CHANGELOG). Guide for wake-on-event:
`docs/NOTIFY-CLAUDE.md`. The author asked for a fresh session instead of compaction: not possible from
inside; a SessionStart(compact) hook that injects HANDOFF.md instead (the author: yes, 10-30; next item 2).

**GPU still in mtw2 mode**: `just gpu shared` in the author's tooling repo when the campaign stops.
Claude usage cap for the day was 12% (the author).

**Next, in order:** 1. start `just watch scratch`; 2. add a Claude Code `SessionStart` hook,
matcher `compact`, for this project that puts HANDOFF.md's top section into the session after a
compaction (and a reminder to restart `just watch scratch`, which a compaction doesn't kill but a new
session needs); use the update-config skill, project `.claude/settings.json`; the author approved 10-30;
then update docs/NOTIFY-CLAUDE.md section 6; 3. papal election results crash (5 so far; cause
unknown, not the shape press); 4. one slow seat blocks the other in the loop; 5. #scratch-audit
alerts (garrison:Nottingham done but didn't move); 6. after the Gemini reset (~10-30 18:10 UTC):
England on Gemini, compare refusals; 7. Heretic help: affordability hints, ready orders, shorter
history, Sonnet examples.

## 2026-10-29 (end of day, Claude usage at 7%): campaign left running on free models

**Running, unattended:** the `scratch` campaign (turn ~52), loop, bot, crash-watch; England and France
both on `heretic:local` (England was on Sonnet for turns 44-51: 15-25 s a turn, 0 checker refusals,
~33% game-side refusals from far fewer orders). The play reviewer is **stopped** (it queued on Heretic).
Reader: `agy:gemini-3.8-flash-low`, out of quota until ~10-30 18:10 UTC (popups fall back to defaults).

**GPU is in mtw2 mode** (Uncle J, PR #239 there): llama-heretic `-c 65536 -np 2 --fit-target 1024`
(2 x 32k, 8.8 GB on the GPU), Ollama and Klarheit's timers paused. France's turns 188-228 s -> 73 s.
**When the campaign stops: `just gpu shared` in the author's tooling repo.** ~1 GB VRAM headroom:
on a CUDA OOM, `HERETIC_FIT=2048 just heretic up -d --force-recreate` there.

**Merged since the evening section:** #200 docs, #201 the bridge's 41 constants in one table `K`
(the main chunk hit Lua's 200-local limit; a reload then failed and needed `just relaunch-game`, which
now has run end to end twice), #202 no-land-path refusal carries the board order or "no fleet", #203
audit: used after merging it away = ruler, #204 buttons pressed by `execute()` (Track A), #205 End
Turn too, #206 renamed captains found by their reported tile (~25 France refusals) and entering a full
own settlement refused (not yet met live).

**Refusals, all 332 this campaign:** treasury too low 26% (ruler), captain renames (bridge, fixed),
merges after moving / over 20 (ruler), sea and foreign-town moves (told the fitting order). Model
matters most: England 7% refused on Gemini (turns 0-4), 34-60% on Heretic, Sonnet 0 checker refusals.

**A crash at turn 47 (14:08):** "unspecified error"; not my probe (control.txt was still unread after
the relaunch). Last bridge line: a papal election results scroll; Proton log shows LuaJIT exception
code 0xe24c4a02 nearby (also thrown for caught errors, so not proof). Look at the papal scroll
handling next.

**Next, in order:** 1. after the Gemini reset: England on `agy:gemini-3.8-flash-medium`, reader on
flash-low, play reviewer back on Gemini; compare refusals with Heretic/Sonnet; 2. the papal-scroll
crash; 3. Track A: decision scrolls (marriage/adoption) by `execute()` on their sub-elements (needs a
live offer to see the parts); `on_pre_battle` still uses a scripted click; 4. "merge Henry into
garrison:York" came back unknown after Henry entered York (explain it in the refusal); 5. The author's
calls: prompt chat-history trim, whether Sonnet is worth its cost for the release.
Gate every reload: `pytest -q > out; s=$?` and a lupa `loadfile` compile check, never `| tail`.

## 2026-10-29 (evening): the turn audit runs every turn; eight more fixes from what it found

**State:** main after this docs PR. **Running:** the `scratch` campaign (turn ~33), the loop and the
bot (both from main), crash-watch, the play reviewer on Heretic. France is now `freeze = true`,
`control = "full"` (its game AI overrode its ruler's moves; bridge logged "france: game AI frozen").

**The turn audit** (the author, 10-29: "why do I have to ask you"): `just audit <name> [game_id]` replays any
run; every turn the loop audits the turns just played, posts each new problem once to
**#scratch-audit** (humans only), and tells each ruler its own ruler/option findings in the next
prompt. Bridge-bug findings per 10 turns are the convergence measure (this run: 12, 5, 19, then turns
30+ after the fixes; run3: 3, 2, 10, 8). Seen keys: `parley_turns/scratch/audit-seen.json`.

**Merged since the last section:** #190 docs, #191 no-land-path refused, #192 recruit upkeep shown,
#193/#194 the audit, #195 moves onto foreign settlements refused with the fitting order, #196 near-miss
names read as the ruler's own (28 past refusals resolved on replay), #197 agent-order refusals name
the field swap, #198 a garrison's move takes only its general (said in a note; move checked by his
name), #199 the audit judges moves two reports on. Each loaded into the running game before merging,
except #194 (the bot needs the main checkout's env file) and #199 (offline).

**Probed live through `control.txt`** (a one-line `lua ...` the bridge runs and logs): long land moves
work; `faction:splitArmy` from a garrison **copies** the unit (York 8 -> 9; the copy was removed again):
never use it for a march-out.

**Ruler quality (Track B) is now the main gap.** Heretic lost London, Nottingham and Caen by turn 31
and repeats refused orders after being told why (sea moves 5 turns running, merges over 20 units).
Open on branch `feat/refusals-carry-the-order` (loaded into the game, not merged): a no-land-path
refusal carries the board order ready to copy; merge once a live refusal shows it and see whether
Heretic copies it.

**Next, in order:** 1. merge the board-order branch after its live check; 2. watch #scratch-audit and
the bridge-bug count for turns 30+; 3. after the Gemini reset (~10-30 18:10 UTC): reader back on
Gemini, Track A (no clicks) Phase 1; 4. decide with the author whether ruler quality needs a stronger model.

## 2026-10-29 (later): fresh campaign running; three fixes checked live and merged

**State:** main after this docs PR. **Running:** the `scratch` campaign (a new England campaign started
today, turn ~16), the turn loop, the Discord bot, crash-watch, and the play reviewer on Heretic
(`uv run python -m parley.play_review games/local/scratch.toml england --every 5 --model heretic:local`).
The previous run is in `parley_turns/scratch.run3*`, the failed first start in `scratch.false-start*`,
and its play reviews in `_review/scratch.run3-reviews/`.

**Seats (`games/local/scratch.toml`):** England brain and decider and France on `heretic:local`; the
reader is `agy:gemini-3.8-flash-low`. **Every Gemini Flash tier is out until ~10-30 18:10 UTC**, so popup
reads fail and fall back to the bridge's defaults until then.

**Process (the author, 2026-10-29: "most efficient course"):** one fix at a time in its own worktree, loaded
with `just reload-bridge`, checked live against the turn folders, then merged. Start the turn loop
before starting a new campaign.

**Merged today:** #187 overview stall (not yet on the real case: a new campaign's turn 1), #188 move
check at the next turn start (live-checked, turns 10-13), #189 `move_agent` refuses sea.

**Next, in order:**
1. Watch the campaign: verify each play review (`_review/*-play-review-scratch-england-t*.md`) against
   the turn folders; fix bridge bugs one at a time as above. The ruler repeats refused orders (a fleet
   onto land twice); that's Track B (ruler quality).
2. Open: Rufus didn't move on the turn a garrison was sent to merge into him (one case). France has no
   `freeze`, so its game AI can override its ruler's moves: The author's call whether to freeze it.
3. After the Gemini reset: reader back on Gemini; Track A (no clicks) Phase 1 from
   `_review/2026-10-27-no-clicks-inventory.md`.
4. Outreach bar (the author, 10-29): 50+ untouched turns, no false reports in prompts, a cheap ruler that
   holds and grows England, the draft in `review/` corrected; roughly 1 of 4 met today.

## 2026-10-29: stuck-army fixes and prompt rules merged; nothing run live yet

**State:** main after the docs PR for this session, 733 tests pass. **Nothing running.** Merged: #182
(`review/` ignored), #183 (ROADMAP: Vox Deorum ideas, ideas only since its code is CC BY-NC-SA), #184
(stuck armies, `_review/stuck-army-2026-10-27/REPORT.md`), #185 (spy and merge_units prompt rules).
**None of #171-#185 has run live**, and `mods/parley` doesn't have #184: run `just install-bridge` first.

**Seats:** `games/local/scratch.toml` is on `heretic:local` (England brain and decider, France) since Flash
quota ran out on 10-27; the reader is still `agy:gemini-3.8-flash-low`. Flash was available again on
10-29. Argon is out until 10-30 17:41 UTC; agy's Claude and gpt-oss models until 11-02.

**Next, in order:**
1. Fresh campaign `scratch.run3`: move `parley_turns/scratch*` (the current run) aside, pick the seats,
   `just install-bridge`, `just play scratch`, `just crash-watch`, `just play-review scratch england`.
   Watch for `MOVES THAT DID NOT HAPPEN` in prompts and the bridge log's "did not happen" lines: they
   will tell whether moves onto own settlements fail for a reason we can fix.
2. Track A (no clicks): agy's inventory `_review/2026-10-27-no-clicks-inventory.md`, Phase 1. Verify
   each claim first (e.g. `run_ui_job` dead, `getUiElement():execute()` for every button).
3. Community outreach waits for a clean campaign (the author, 10-29). agy's draft is in `review/`; several
   claims in it are wrong or unverified.

Play review notes: the turn-40 review's "agent loss reported a turn late" was wrong (Geoffrey Grey died
after the turn-37 report was written); verify review claims against the turn folders before acting.

## 2026-10-26 (evening): play moved off Claude; agy watches, diagnoses and fixes

**State:** main after this docs PR, 711 tests pass. **Nothing running** (loop, bot, crash-watch and play
reviewer stopped for the night). The `scratch` campaign ended: victory conditions failed (~turn 106,
England down to 2 settlements, -16,000 florins); the game sits on that screen. Seats in
`games/local/scratch.toml` stay on agy: England brain `agy:gemini-3.8-flash-medium`, decider and France
`agy:gemini-3.8-flash-low`, `reader = "agy:gemini-3.8-flash-low"`. To resume: new England campaign (move
`parley_turns/scratch*` aside first, as `scratch.run2`), `just play scratch`, `just crash-watch`,
`just play-review scratch england`.

**The author, 2026-10-26:** save Claude usage, put play on agy; relaunch the game yourself after a crash; if a
ruler plays stupid, have agy find out why; an agy watcher should watch the play.

**Done (merged):** #168/#173 `just relaunch-game` and `just crash-watch`; #169/#170 play reviewer; #171
decision buttons hidden or faked by settlement labels (turn-60 stall; also the likely trigger of the turn-50
crash: an undetected guild offer, then a minimized scroll forced open over it); #172 crossings name each
shore's land tile, leaderless fleets resolve; #174 reader on agy; #175 stars counted from pixels (Gemini
undercounts by one; the record is all zeros); #176 the Gemini loop (below).

**Gemini as ruler (turns 51-106):** flash-low (no thinking) took England from 7 settlements, +6,000 (turn
60) to 2, -12,000, one order a turn. agy's diagnosis, verified: an every-turn merge rule plus merges that
moved nothing reported "done", debt refusing every gold order with no free lever named, and notes copied
forward turn after turn. flash-medium thinks (~4,700 tokens) but still gave one order until #176. After
#176: refused empty merges, set_tax used; still thin.

**Next, in order:**
1. Judge Gemini fairly: a fresh campaign with #171-#176 in from turn 1 (this one is past saving). If it
   still plays thin, feed back only the last note (agy's fix: YOUR RECENT NOTES feeds 5 near-copies).
2. Read the play reviews in `_review/` (t0069...); verify each claim before acting.
3. `just relaunch-game` has not yet run end to end (Steam -> Run mod); the next crash tests it.
4. The older items below (ransom captive wording, Argon after ~10-30, upstream #89/#90, X1 duplicates).

## 2026-10-26 (late afternoon): live steward test, scratch restarted as a new England campaign

**State:** main after #163, 682 tests pass. `scratch` is a NEW England campaign (started 13:05; the old
scratch turn folders and db are moved to `parley_turns/scratch.run1*`, nothing deleted). The game,
loop and bot keep running under autoplay; England has `quiet_brain = "agy:gemini-3.8-flash-low"` in
`games/local/scratch.toml` (a test line; remove it when done).

**Verified live:** the steward escalates; repair works (turn 21, Edinburgh small_church, 5441 -> 5313
florins, no longer damaged); the ruler answers technical notes plainly (Mantle correction, turn 11).

**Fixed live (merged):**
- #159: the game's suitor record is all-zero at offer time; the steward declined two good suitors on
  "command 0, loyalty 0". An all-zero record now counts as unknown and goes to the ruler.
- #160, #163: rulers know they're an AI playing through Parley, answer technical notes out of character
  ("Bug: <what>" in the note), and know Claude is the developer who runs it.
- #161: the ruler's record of a named choice keeps what the scroll showed (turn 8: it forgot its own
  ceasefire with Scotland, blamed the game's AI, and re-declared war).
- #162: the turn gate counted the ruler's own and old messages (`Store.recent` = last 30 of any turn),
  so every turn escalated. Now only others' messages since its last turn count. France writes to England
  almost every turn, so the cheap brain still rarely plays: expected, not a bug.

- #165: `find_choice` took settlement labels (green faces, red beside them) for a decision's check
  and X, so stuck recovery sent phantom decisions to the ruler and never reopened the minimized
  "Bride Presented" scroll (turn 27, 10 min, a hand click). Buttons must now sit on parchment
  (checked on ~1700 live captures: all 123 real decisions kept). Stuck turns now clear in 1-2 tries.
- #166 (bridge, reloaded live at turn 37): a fleet ordered onto land is told the nearest sea (turns
  32-34: three guesses at one coast); a garrison merging into a distant army is told it marches out
  under a captain and leaves its town empty (turn 12, Edinburgh).

**Next, in order:**
1. **`just install-bridge` doesn't reach a running game**: it loads at launch; use `just
   reload-bridge`, only with no popup on screen (a reload at turn 7 dropped an open marriage scroll).
   When scripting the check, strip the `\r` from `system.log.txt` lines.
2. Duplicate readings (defect X1) still live: one mission or sack choice is read up to 5 times.
3. The cheap brain hasn't played a turn: France writes to England nearly every turn, a real reason.
   Remove `quiet_brain` from `games/local/scratch.toml` when done testing.
4. Items 2-5 of the list below (ransom wording, Argon after ~10-30, upstream #89/#90, traits/event ids).

## 2026-10-26 (afternoon): the steward grows, a turn gate, Heretic can play

**State:** main after this docs PR, 668 tests pass. Nothing running. The game's installed bridge
predates the repair order (#157): run `just install-bridge` before live tests. The author, 2026-10-26: Claude usage runs out before Wednesday: offload everything possible to
agy (Gemini writes code, tests, docs; Claude specs, gates on tests, reads diffs, merges). Saved games
don't matter for now: live tests may use and overwrite any save, scratch2 included.

**Next session, in order:**
0. **Live steward test, Claude driving the game alone** (the author is away; saves don't matter): run
   `scratch` (England = player slot, ladder on) for several turns; after each turn read
   `just decisions scratch` and the ruler's game messages; check each steward answer against the
   scroll. Also set `quiet_brain = "agy:gemini-3.8-flash-low"` on England for a few turns to see the
   gate live.
1. **Test the repair order live** (#157, merged; damaged buildings in the report, `repair` order) on
   a damaged building, after `just install-bridge`.
2. **Live-check the ransom captive scroll's wording** (never captured; its parse is unverified).
3. **Argon seat test after ~10-30** (`just seat-bench` on a fresh turn).
4. **Watch upstream #89/#90**; when llama.cpp#30528 merges, the Refinery bumps Heretic's image.
5. **Remaining items from previous list:**
   - Score traits next (unscored today); calibrate `ADOPTION_SCALE` and the 0.2 margin from real offers.
   - Event ids: log mining is not viable (`_review/2026-10-26-gemini-event-ids.md`); try
     `M2TWEOP.condition("Event <name>", e)` live, one probe at a time on a save copy, or log the
     eventID with each reading going forward.
   - Click debt and next deciders from `docs/decision-inventory.md`.

**The steward and popups:**
- Marriage offers (`parley/deciders/marriage.py`, #150) and ransom scrolls (`parley/deciders/ransom.py`,
  #152) join adoption under `_steward(kind, ...)`. Ransoms: captor ransoms by custom under 1,500
  florins; captive pays or refuses by price versus treasury; execute and release always escalate to the
  ruler.
- In `games/local/scratch.toml`, England (the player slot under autoplay) has `ladder = true`. In
  `scratch2` England is AI-run, so popups never reach it; the steward only matters for the player slot.
  Neither scratch game has a decision log yet (logging began after their last turns).
- Every steward decision records its on-screen outcome in the decision log (#154), using Jigsaw's
  `Verdict.decision_id` (jigsaw#9).
- `just decisions <name> [last]` (#151) reports decision history from `<turn_root>/<game>.decisions.db`
  by rung, kind, actor, and newest decisions with outcome and escalation reason.

**The turn gate (#155):**
- For `ladder = true` seats with `quiet_brain` set, quiet turns go to the cheap brain (`parley/turn_gate.py`).
- Reasons escalating to the ruler: messages, popups, events, enemy within 8 tiles, siege, money, every
  5th turn, and 2 quiet turns in a row. Each gated turn logs a `turn_gate` decision.
- Not yet run live; no seat sets `quiet_brain` yet.

**Seats and benching (scratch2 England turn 24, 53 KB prompt):**
- `heretic:local` / `openai:<model>` (#153): OpenAI-compatible seat talking to llama-server on :8090,
  with wait-and-retry on 503 or dropped connection. Bench: 623 s, 16 kept, 4 rejected, 0 malformed:
  best non-Claude order quality, but far past the 240 s seat timeout while the game shares the GPU.
  Heretic's wake from sleep can abort on CUDA OOM (llama.cpp re-uses its boot-time fit; upstream
  ggml-org/llama.cpp#30528 open); Refinery #216 added a retry in ask_heretic.
- Seats through agy: `flash-low` 47 s, 7 kept, 0 rejected, 0 malformed; `flash-medium` 201 s, 6/0/0
  (shared slots); `flash-high` 302 s, 2 kept, 6 malformed; `gpt-oss-120b-medium` alone 293 s, 1 kept,
  2 malformed; argon low/medium/high all "agy status ERROR" (weekly quota, resets ~2026-10-30).

**Upstream and gaps:**
- EOP-Labs/M2TWEOP-library#89 feature request (missions list, hiring mercenaries, diplomatic proposals,
  games/races, agent recruit cost, siege equipment); #90 the fix PR for #88 (`getBuildingInQueue`),
  compile-tested on the Gitea Windows runner (run 2255), not run in game.
- Gap audit found master already exposes retraining (we already do it by direct write) and repair
  (construction options + `addBuildingToQueue`). Decision inventory refreshed (#156).
- Repair order (R3, #157): damaged buildings (hp below 100) in the report; `repair` queues the game's repair option. Not yet run in game.
- Refinery #215: agy may run `which`, `realpath`, `git grep`, etc. (a marriage job had died on `which`).

## 2026-10-26: Jigsaw (algorithms first, LLM when needed); Gemini fully unblocked

**State:** main after PR #149 (docs), 596 tests pass. Nothing running. `scratch2` untouched (a live
test this morning ran on a copy; turn folders and saves restored byte-identical). Bridge installed
with today's changes (watchdog, treaties, recruit queue, fleet guards).

**New project: Jigsaw**, `../jigsaw` (private Gitea `author/jigsaw`, GPL-3.0). Design:
`docs/specs/2026-10-26-jigsaw-design.md` (draft 2). Built: decision log (thread-safe), ladder and
gate. Parley imports it (non-editable path dependency: after Jigsaw changes run
`uv sync --reinstall-package jigsaw`; it must become a git/PyPI dependency before going public).

**Gemini now:** writes and tests code in a worktree (`sandbox-run`, offline bubblewrap), reads the
web (agy-only `fetch` MCP, `raw: true`), and habitual commands (python3, find, sed, jq...) are
sandboxed shims on its PATH (Refinery #208, #209, #210, #213). **Restart the session** so the
delegate MCP server loads the new `ask_agy.py`; until then run agy through
`the author's tooling repo/.venv/bin/python scripts/ask_agy.py --cwd <worktree> --edits
--model gemini-3.8-flash-medium --prompt-file <file>`. Argon's weekly cap resets ~10-30 14:00.
In mtw2 worktrees: `uv sync` on the host first, Gemini tests with `sandbox-run .venv/bin/pytest -q`.

**Next session, in order:**
0. **Marriage steward** (same shape as adoption; a Gemini job died on its first command,
   `which sandbox-run`): allow `command(which)` in the Refinery's agy permissions, then rerun the
   Gemini spec in `_review/2026-10-26-marriage-steward-spec.md` (score_marriage: decline baseline
   8, age > 60 costs 3, stakes 0.3; `_steward_adoption` generalised into `_steward(kind, ...)`).
1. **Try the steward live:** `ladder = true` under a seat (e.g. England) in `games/local/scratch2.toml`
   (the author's call), then read `scratch2.decisions.db` (`rung_counts`) and the ruler's messages. Score
   traits next (unscored today); calibrate `ADOPTION_SCALE` and the 0.2 margin from real offers.
2. **Next deciders, each with its adapter row** (`docs/decision-inventory.md`): ransoms, then the
   click debt. Event ids: log mining is not viable
   (`_review/2026-10-26-gemini-event-ids.md`); try `M2TWEOP.condition("Event <name>", e)` live, one
   probe at a time on a save copy, or log the eventID with each reading going forward.
3. **Decision outcomes** are recorded (#148); next, outcomes for steward decisions (the click's
   result) and a `just decisions <game>` recipe over the log.
4. **Gate in front of the ruler's turn** (Jigsaw build step 3, cost cutting): quiet turns get a
   cheap note instead of a full Opus call.
5. Upstream contributions (each needs the author's OK, public): a PR for #88's fix; the event-id table
   once named; the decision-inventory gaps as feature requests.
6. Gemini seat test after Argon resets (seats must survive bad decisions: PR #140 covers parsing).

## 2026-10-25 (night): the game runs EOP master; its crash found and fixed

**State:** main after PR #136 (this docs PR), 536 tests pass. The game is on **EOP master**
(upstream CI build b525628) as `mods/parley`; 3.3.1 is parked as `mods/parley-331`. The author's campaign
`scratch2` (the author plays HRE; England = Scratch on `claude:opus`, full control, not frozen; France =
Philip on `claude:sonnet`) is saved as `author-hre-turn27` in master's saves, loaded with the bridge
running, at HRE's turn 27. The loop and bot are stopped for the night: `just play scratch2`, then
load `author-hre-turn27`.

**The master crash (PR #135):** bisected live by driving the game (launch through Steam, "Run mod" in
the EOP launcher, load, End Turn, read logs). A Lua line trace (`debug.sethook`) over England's
turn end stopped at `queue_of`: master's `getBuildingInQueue(i)` returns `buildingQueue[i]` of a
circular buffer indexed from its head (`types/settlement.cpp:972`) though documented 1-based, so
`i = n` is an empty slot and its name read kills the game. The bridge reads `1..n-1` on master.
Verified: two full rounds with rulers answering and orders applied (merge, move_agent, recruit).

**Next session, in order:**
1. **Upstream issue for `getBuildingInQueue`** (needs the author's OK: public, his account): cause,
   file:line, one-line fix (`position - 1`), the repro (any faction with a queued building).
2. **Freeze done right:** a frozen faction's turn never ends (live, turn 20: its frozen AI never
   answered its own siege). The bridge must unfreeze the seat as its turn ends (or after orders),
   then refreeze at its next start; test on a save copy with a siege running. England is not frozen.
3. **Master's new calls for our gaps** (`_review/2026-10-25-gemini-eop-master-port.md` §3):
   treaties (`campaign:getFactionDiplomacy`), heir/leader, capital, recruitment queue
   (`getUnitInQueue`), agent recruit cost. Behaviour change to watch: master's `setDipStance` runs a
   console command (`diplomatic_stance ...`), not a direct write.
4. Gemini seat test after Argon's quota resets (~2026-10-30 13:40). Webhook command (the author).

**Driving the game yourself** (the author asked for it): window `Medieval 2` at (4,30) 1600x900; Steam
`steam://rungameid/4700` opens the EOP launcher (window `M2TWEOP`, "Run mod" at screen 956,534);
main menu Load Game 376,488 → Load Campaign Game 376,298 → list rows ~20 px apart from y 274 (in-game
menu) or 330 (main menu) → Load; End Turn 1550,760; crash dialog OK 960,551. Screenshots:
`import -window root -crop 1610x935+0+0`. Never `rm -rf` (denied); never EOP `saveGame`.

## 2026-10-25 (afternoon): scratch2 live (the author plays HRE); crash guards in; EOP master parked

**State:** main after PR #132, 534 tests pass. The game runs **EOP 3.3.1** (`mods/parley`) with
`games/local/scratch2.toml`: The author plays HRE himself (no autoplay), England is Old Scratch on
`claude:opus` (full control, a non-player faction now), France is Philip on `claude:sonnet`. At
turn 10, no crash since the rollback. scratch ended at turn 226 (victory conditions failed).

**Next session, in order:**
1. **EOP master crash, on a save copy, never in the author's game.** The official CI build b525628 is
   parked as `mods/parley-master` (bridge installed in its `eopData/eopScripts`, `parley_turns`
   linked). It crashed six times at England's turn start right after its own "Try attack army
   order" log lines, with no bridge orders. Swap = two renames with the game closed. Check
   whether master's campaign-AI changes (the attack-order log) crash on their own (a vanilla save,
   no bridge), then report upstream if so. The port plan: `_review/2026-10-25-gemini-eop-master-port.md`
   (Gemini's; its rename map checked: only land crossings differ by name, PR #127 done).
2. **Gemini seat test** when Argon's weekly quota resets (~2026-10-30 13:40): `just seat-bench`
   on hung turns, then argon-medium on France with `fallback = "claude:sonnet"` for 30+ turns.
   Flash is not a ruler (0 orders) and not an autonomous coder (give it exact single edits).
3. **Webhook (the author):** `workflow_job` hook on `author/M2TWEOP-library`; the command is in this
   session's transcript (prompts for foc's secret, URL `http://<gitea-host>:8712/`).
4. The ROADMAP's decision-tracking design (discuss with the author) and the decision inventory refresh.

**Live crash classes, all guarded now:** an instant merge into a besieging or moving stack (#126);
`siegeSettlement` from more than one tile (#130); an agent action from inside or far from its
target (#131). EOP's calls check no range: any new order that calls an EOP action must check
range and state first.

**Quirks:** `training.json` is per game now (#132). France's Gemini runs left `fallback` docs in
WRITEUP. The shared bot and loop: `just play scratch2`. Rulers keep re-issuing refused orders
(Richard's spy); the refusal reasons reach them each turn.

## 2026-10-25 (later): primer, plan, agents, lessons, queue merged; EOP builds on the runner

**State:** main after PR #117, 513 tests pass. The game is stopped. Nothing below has run live yet.
**Start fresh:** the author took mtw2 off the Refinery's delegate local-only list (Refinery PR #204).
A new session gets the `delegate` MCP (`ask_agy`, pass `model="gemini-4-argon-high"`); only the
env file stays blocked. agy's own read_file deny on mtw2 is still on (the author's call), so paste code
into Gemini prompts.

**Merged this session:**
- #110: the strategy primer in every prompt, fact-fixed before wiring; the standing plan
  (`"plan"`, shown every turn).
- #111 and #113: `recruit_agent`, by the game's rules. A building must grant the agent
  (`getAgentCapability`), the faction limit is the sum of `getAgentLimitCapability`, and the
  price comes from `descr_cultures.txt`. Next turn `spawn_character` places him.
- #112: the lessons store, per persona (keyed by the seat's display name), reviewed every 20
  turns in a background thread. `just lessons <game>` lists them, `just lessons-veto <game> <id>`
  removes one. Gemini seats measured: `agy:gemini-4-argon-medium` is clean on England's full turn.
- #114: the recruitment queue. 9 waiting at most; beyond the training slots, recruits wait.
- #115: `just seat-bench <turn dir> <timeout> <specs…>` replays a played turn to seats.

**First live session, watch in this order (one change at a time):**
1. The report's "can train agents" and "AGENT LIMITS". Check that `getAgentCapability(t).value
   > 0` matches what the game's recruitment panel offers. Then one `recruit_agent`; the next turn
   the log should say "<agent> trained in <settlement>", or "UNCONFIRMED".
2. The standing plan appears and carries over. The primer shows up in `prompt.txt`.
3. At turn 180 (the next multiple of 20), the log line "lessons review at turn 180 kept N".
   Then `just lessons scratch`.
4. Optional: a seat on `agy:gemini-4-argon-medium` (the author's call which seat), to save Claude usage.

**EOP builds (fork `author/M2TWEOP-library`, private):**
- Branch `gitea-ci` holds `.gitea/workflows/build.yml`. It mirrors upstream's build (msbuild
  library, GUI and d3d9, Release x86) and unpacks the DirectX June 2010 SDK in the job, checked
  by Authenticode, with portable 7-Zip pinned by SHA256.
- **Green:** run 573 built EOP master in 13.5 min and produced `M2TWEOP.zip` (96 MB) as an
  artifact, in the run's UI. Run 574 built branch `lua-culture-agent-cost` green too. Run 571
  had failed on a dead 7-Zip URL, since fixed. The SDK is now cached at
  `C:\Users\runner\eop-cache\dxsdk-jun10`, trusted only with its marker (gitea's conditions).
  Thread: `_review/2026-10-25-gitea-*eop*`.
- **needs-author:** the VM auto-starts only for `author/foc`. A `workflow_job` webhook on
  `author/M2TWEOP-library`, with foc's URL and secret, needs the author (the secret is credential-guarded).
  Until then, ask the gitea session to start the VM.
- Branch `lua-culture-agent-cost`: `M2TWEOP.getAgentRecruitCost/Time` from the culture DB, the
  first upstream candidate. It can't be verified until we run an EOP master build in the game,
  and that upgrade is the author's call.

**Still open from the ROADMAP:** parity for AI-run seats. The game decides family offers, votes
and AI offers silently for them. EOP master has only notifications plus `characterRecord:marryWife`,
so a live probe must first show whether `onOfferedForMarriage` fires before the AI decides. Then
the EOP master port, then the freeze.

## 2026-10-25 (end): game stopped; primer, plan and EOP builds queued

**State:** main after PR #108, all merged, 486 tests passed at the last full run. The author stopped the
scratch game (England Opus, France Sonnet). Claude's weekly usage was at 74%, so hand work to Gemini
(`agy --model gemini-4-argon-high`, code pasted in, tests as the gate).

**Pick up here, in order:**
1. **Primer + standing plan.** `parley/primer.md` is committed but not yet wired in. Gemini's answers
   (spec + code, unreviewed) are in `_review/2026-10-25-gemini-wire-answer.md` (primer into
   `build_prompt`) and `_review/2026-10-25-gemini-plan-answer.md` (`Orders.plan`,
   `Orchestrator._last_plan`, a plan section in the prompt). Review them, apply, `just test`, one PR.
2. **EOP builds on the Gitea Windows runner.** The thread is in `the Gitea admin folder/review/` and
   `_review/` (`2026-10-25-*windows-runner-msvc.md`). The runner already has MSVC v143 and SDK 22621.
   Next: create the Gitea repo `author/M2TWEOP-library` (fork of EOP-Labs), add a minimal
   `runs-on: windows` msbuild workflow (job-scoped env only, VS stays 2022), run it, and post the
   log to gitea's review folder. Doorbell: SendMessage `gitea-dc`.
3. Then the agreed list in ROADMAP "Next": agent recruitment via `spawn_character` with the game's
   rules, parity for AI-run seats, fixing Gemini seats (try gemini-4-argon), and a cross-game lessons
   store.

## 2026-10-24: observer mode live: Old Scratch plays England, the author advises

**State (end of session):** `games/local/scratch.toml` is running, at turn 23. It has 18 LLM rulers;
the Gemini seats were moved to Claude Haiku mid-game. Old Scratch (Opus, `control = "full"`,
adviser `your_discord_name`) plays England, the human slot, under autoplay. He holds York, Rennes and
Bruges, the last two bought by bribe. PRs #13–#39 are merged, 398 tests pass, `main` is clean.
The day's story is in `docs/JOURNAL.md`; the guide is `docs/WRITEUP.md` §0 and §9.

**The QA loop (Claude can run it without the author):**
- `just follow england scratch` streams the ruler's messages and notes. Claude re-arms it as a
  background `--once` watcher.
- `just reload-bridge` hot-reloads the bridge into the running game through EOP's `restartLua`,
  which needs `enableConsole = 1`. Orders already applied aren't applied again.
- `just restart-loop scratch` restarts only the turn loop; the bot and its token are untouched.
- `parley_turns/control.txt` takes four commands:
  - `reload`
  - `scan <label>`: every open UI element, with positions
  - `script <campaign command>`
  - `lua <one line>`: a live probe, whose result is logged in `parley_bridge.log`
- `just tell england scratch "…"` sends the ruler an out-of-character game note.
- A full relaunch is needed only after a crash. Don't use EOP's `saveGame`: it hung the game.

**Built today (beyond the observer-mode list):**
- recruiting from the recruitment pools
- the income figure split from one-off spending
- agent mission outcomes, with EOP's disaster-name bug translated
- popups read from screenshots by Haiku, with the turn loop's own thread
- marriage offers decided by the ruler and clicked (window focus needed)
- ships: `board`, `land`, `blockade` (only the tile and port lookups are verified live)
- the duplicate-build refusal
- readable notes
- `just tell`
- game notes

**Next (suggested order)**
1. **Family, and why agents and family die** (the author's request). The report has no family, so
   Cecilia's death went unnoticed until Scratch asked.
   - List the family from `fac:getNamedCharacter(i)` (the dead and off-map ones included):
     name, age, role, alive, married to whom, and princesses with their marriage prospects.
   - When an agent or family member disappears, give the ruler the full list of plausible causes
     for that kind of character, ordered by evidence, and ask him to theorize. Causes overlap:
     - old age (compare against the age at last report)
     - assassination (enemy assassins seen nearby; any `onAssassinationMission` event naming the
       victim)
     - battle death (a battle that turn)
     - plague, or failing a mission (spies and assassins can die in a failed attempt)
     - for a princess: married off (spouse field, or no longer in the list as ours)
     - bribed away (now listed under another faction)
   - The author suspects Cecilia, dead at 36, was murdered.
2. **AI diplomatic offers decided by the ruler**, like marriages. The screen reading can now show
   the terms. Click accept or decline as with the marriage scroll (measure the buttons from a
   screenshot).
3. **Ships live:** watch Scratch's first board, sail and land. Fix whatever the move-based boarding
   does in practice.
4. **Garrison marching:** confirm that `merge_armies` brings a garrison to a field army.
5. **Parley window width** (its lines are cut off). Make the seal finder's size limit relative to
   the window.
6. **Unit queue slot limit** for recruiting (not modelled).

## 2026-10-23 (end of day): Plans 1–2 done and playable; persona library; full write-up

**State:** playable end to end on the author's Linux machine.
- **Game side:** EOP 3.3.1 in `mods/parley`, launched through a Steam launch-option swap. The
  Lua bridge reports at turn end and applies orders at turn start, and never blocks. All 8 order
  types are verified in game.
- **LLM side:** Claude (CLI), Gemini (`agy`, flash-**low**) and Ollama seats.
- **Memory:** each ruler's last 5 notes plus what changed since its last turn, and the
  diplomacy so far.
- **Discord table:**
  - a public channel per game (`#<game-id>`), private threads via `!private <faction>`;
  - replies between turns, grounded in the ruler's real report;
  - turn cues, and transfer notices in private threads only.
- **Persona library:** the 1080 historic roster plus 6 archetypes, used with `persona = "@id"`.
- Tests: 168 passing. Guide: `docs/WRITEUP.md`. Build log: `docs/JOURNAL.md`.

**How to play:** `docs/WRITEUP.md` §5.
1. `just run games/historic-1080.toml`
2. `just discord games/historic-1080.toml`, in the author's own terminal, since it reads the token.
3. Steam Play → Run Mod → new campaign as England.

**Live game in progress:** `games/first-game.toml`.
- England (the author) owes Venice 600 florins by turn 20 or 21. Venice sent 500 on turn 16.
- Milan was switched to Gemini flash-low.

**Next (suggested order)**
1. **A richer report:** foreign armies near the ruler's lands, neighbours' settlements, real
   income. That cures invented place names and blind threats.
2. **Plan 3, the deal ledger:**
   - human `/send` and `/cede` with travel time;
   - deals recorded from chat;
   - kept or broken checked against the game, with a public record.
3. **Plan 4, cross-game memory for permanent personas,** with `forget`.
4. **A bigger game** with `games/historic-1080.toml`, then scenarios (Plan 5).
5. **An automated installer** from `docs/WRITEUP.md` §4.

**Known issues**
- Public M2EX has no Lua; v1 runs on EOP.
- Gemini flash-medium returns empty structured answers; use flash-low. agy calls queue
  machine-wide.
- Rulers sometimes repeat lobby messages.
- `income` and `visible_enemies` aren't populated by the bridge yet.
- The deferred review minors are in `.superpowers/sdd/*/progress.md` and the PR descriptions.

## Checkpoint 11-01 ~08:40 (stopped early: machine out of memory)

Branch `fix/qa-open-cases` (not merged, not live-checked with `just qa`):
- The 06:05 baseline exit code 1 comes from `marry_foreign_general`, the only `fail`
  (`parley/qa/__main__.py:75` exits 1 only on a `fail`).
- `repair_queued` cause found and proven live: EOP caches a town's construction options by
  (buildings + queue hash, turn) (`M2TWEOP library/types/settlement.cpp:1008`). Setting `hp`
  changes neither, so no repair shows up until next turn. In Dijon a bump of `turnNumber` by
  one, then a query, then the restore, then a second query listed both repairs. `M.qa.damage`
  now does that. Next: `just qa towns case=repair_queued`. Also make the fake game in
  `tests/test_qa_towns_lua.py` cache like EOP. A first try keyed on `FAKE.gd` broke 5 tests
  and was reverted.
- `marry_foreign_general` and `crossing_in_one_turn` still need a diagnosis. Both agy calls
  failed: argon-high quota is gone for ~5 days, and Flash timed out and was denied `git log`.
- The scratch turn loop and bot are stopped (`just stop`). Restart with `just play scratch`.
