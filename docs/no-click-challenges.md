# No-click play: what still needs a screen click, and how you can help

Parley is an open-source project where LLM rulers play Medieval II: Total War campaigns with no human at
the keyboard. They act through the M2TWEOP (EOP) library's Lua API. The goal is zero screen input: every
decision the game asks for is made from Lua, never by a mouse click or a key press.

## How it works now

A Lua bridge inside EOP (`lua/parley_bridge.lua`) reads the game and applies the rulers' orders. Most popups
are already handled there: `gameSTDUI.getUiElement(name):execute()` presses a named button, and
`stratmap.game.scriptCommand("clear_messages", "")` clears plain notices.

A Python turn loop (`parley/popups.py`) screenshots what the bridge can't close. For those screens it still
clicks with `xdotool` or presses Escape. That is what this list is about.

## Measuring it

- `just qa <suite> kind=noclick` runs every QA bench case with all X input refused. A case that passes needs
  no click. A failing case names the click it wanted in `logs/qa-<suite>-turns.log` ("X input refused").
- `just click-census` tallies every click or Escape the turn loop made or tried, from its logs. Each one is an
  `x-input:` line with the action, the request kind, the game's message event number and the scroll.
- A bench case whose subject is a click carries `needs_click = "<reason>"` in `games/qa/*.toml`. A noclick
  run reports it skipped with that reason.

Forcing tools (the bench creates each situation on demand):

- `M.qa.force_offer(faction, "wife" | "suitor")` opens a marriage or suitor offer with no roll.
- `games/qa/forced.toml`: plague, flood, earthquake, the leader's death, jihad, crusade, a spy report, an AI
  attack, an AI siege, a captured town, men captured.
- `M.qa.parley` opens the diplomacy screen.
- `games/qa/popups.toml`: the papal election cases.

## Status (2026-11-14)

On the bench, with every click refused, 52 of 65 cases ran so far pass. 6 marriage cases are click-only. 4
AI-offer cases are inconclusive (no AI offer came). 3 failures are being fixed.

In one day of live play the turn loop still made these screen inputs:

| What | Per day | Input |
| --- | ---: | --- |
| A message scroll acknowledged by its check button | 166 | click |
| A minimized message reopened on a stuck turn | 122 | click |
| A marriage offer decided | 61 | Escape (accepts then marry in Lua with `marryWife`) |
| An adoption offer decided | 13 | click |
| A papal election vote | 1 | click |

## Open challenges

Each one: what clicks today, why Lua can't yet, the leads, how to force it, and how to prove a fix. The proof
is always the same: a `kind=noclick` bench case that passes, and `just click-census` showing that input gone.

### 1. Message scrolls with only a check button (166 a day)

- **Today:** the turn loop finds the check in a screenshot and clicks it.
- **Why not Lua yet:** these scrolls aren't reached by any name the bridge knows.
- **Leads:** the game executable contains the UI names `close_tick_button`, `clear_message_button`,
  `message_show_me_more_button` and `message_zoom_button`. EOP's `uiElement` has `subElementsNum`,
  `getSubElement(i)`, `execute()` and `xPos`/`yPos`/`xSize`/`ySize`, so an unnamed button under a named
  parent can be found and pressed. A probe that tries every `*_button`/`*_scroll` name in the executable
  while a scroll is open is the first step.
- **Probe result (2026-11-14 13:13-13:16, live, the test laptop):** all 192 `*_button/_scroll/_panel/_listview/_window`
  names in `medieval2.exe` were tried with `getUiElement` four times at 13:16:24-28, right after a forced suitor
  offer (13:16:23). The turn loop's screenshots saw one game scroll on screen throughout (13:16:16-32), so a
  scroll was open; which one (the offer or a notice) isn't logged. Only 7 HUD buttons answered (construction, faction, finances, mission, radar
  zoom in/out, recruitment), the same as with nothing open, and none has children (`subElementsNum` 0). So these
  scrolls are not reachable by name or as named children. **Wanted from EOP:** a way to list the open top-level
  UI elements (or the current message scroll) so Lua can find and press their buttons.
- **Force it:** the disaster cases in `forced.toml` raise message scrolls.

### 2. A minimized message reopened on a stuck turn (122 a day)

- **Today:** when End Turn is blocked by a minimized notice, the turn loop clicks it open.
- **Why not Lua yet:** no call found that restores or clears one minimized message.
- **Leads:** the same UI traversal, from the HUD's message area.

### 3. Marriage and suitor offers (61 a day)

- **Today:** a wife offer is declined with Escape, or accepted with Escape and then `characterRecord:marryWife`
  in Lua. A suitor for a princess can only be accepted by a click.
- **Why not Lua yet:** EOP's `onOfferedForMarriage` event has no accept or decline, and its return value is
  discarded. `marryWife` works for men only. No EOP call marries a princess to a generated suitor. UI scans
  with the offer open found no element by name.
- **Leads:** `perform_marriage_button` (a name in the executable) did not answer with a suitor offer open
  (probe, 11-14 13:16; see challenge 1), and no named parent has children. The EOP element list wanted in
  challenge 1 would cover this too.
  Or prevent the offers: `campaignDb.familyTree.maxAgeForMarriageMale` and `maxAgeForMarriageForFemale` set
  to 0 stop them (the bench does this), at the cost of the ruler's choice of suitor.
- **Force it:** `M.qa.force_offer("england", "wife")` or `"suitor"`.

### 4. Adoption offers (13 a day)

- **Today:** accepted or declined by a click.
- **Why not Lua yet:** the same shape as marriage offers; EOP has no accept or decline.
- **Leads:** `minAdoptionAge`/`maxAdoptionAge` prevent the offers. `characterRecord.isFamily` is writable
  and `factionStruct:spawnArmy` has a `family` flag, so a Lua "adoption" may be possible.
- **Force it:** no tool yet. EOP has no adoption twin of `createMessageMarriageProposal`; one would help.

### 5. The papal election vote (1 a day)

- **Today:** the ruler's cardinals vote by clicks on the election scroll.
- **Why not Lua yet:** touching the papal scrolls inside their own open event hung the game.
- **Leads:** `cardinal.voteFactionID` and `cardinal.isPreferati` are writable (EOP `types/campaign.cpp`), and
  `M2TWEOP.getOptions2().disablePapalElections` exists. Untested: whether the game keeps a vote written from
  Lua.
- **Force it:** the papal election cases in `popups.toml`.

### 6. AI diplomatic offers

- **Today:** answering one is solved: `diplomacy_accept_offer_button` and `diplomacy_decline_offer_button`
  are named and the bridge presses them.
- **Why it's open:** there is no EOP way to make an AI faction propose on demand, so the bench can't force
  one, and those cases come out inconclusive.
- **Leads:** wanted, a way to start an AI proposal from Lua (or a save with one pending).

## How to start

1. Clone the repository and run `just --list`.
2. Read the newest spec in `docs/superpowers/specs/`.
3. Run `just qa smoke kind=noclick`.
4. Pick a challenge. Write the noclick bench case first, then the fix.

Fixes to EOP itself belong upstream, in the M2TWEOP project.
