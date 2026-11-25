# No-click play: how the game is played with no screen input

Parley's LLM rulers play Medieval II: Total War campaigns with nobody at the keyboard. Every
decision the game asks for is made from Lua, through the M2TWEOP (EOP) library, never by a mouse
click or a key press. Since 2026-11-22 that holds for every pop-up we have met in live play, and
the screen-click code has been deleted (#689).

## How each pop-up is answered

The Lua bridge (`lua/parley_bridge.lua`) presses a pop-up's parts as UI elements. Some of this needs
bindings that only our EOP fork has (build `parley-fork6`, forkLevel 6; `just install-eop`
installs it).

| Pop-up | How | Since |
| --- | --- | --- |
| Plain notices | `stratmap.game.scriptCommand("clear_messages", "")` | early |
| Named buttons (AI diplomatic offers, sieges, ransoms) | `gameSTDUI.getUiElement(name):execute()` | early |
| Marriage, suitor and adoption offers | the ruler decides; the bridge presses accept or decline by its element | 2026-11-15 |
| A minimized message holding up End Turn | the fork's `uiElementStruct:activate()` opens its icon | 2026-11-20 |
| The papal election vote | presses the ruler's candidate, only on parts of class `UI::VOTE_BUTTON` (#659) | 2026-11-20 |
| A papal results scroll that stays open | `activate()` on its `SCROLL_CLOSE_GADGET` (#693) | 2026-11-22 |
| The pre-battle panel | the game's own script command presses **Auto-resolve** | early |

Rule learned the hard way: `execute()` works only on buttons. On a message icon it calls a slot the
icon doesn't have, and the game crashes (2026-11-19 and 11-20). Use `activate()` for anything else.

## What still comes from outside the game

Only crash recovery. After a crash, crash-watch closes Windows' error box and puts the game window
back in front, then relaunches the game on the last save.

## Measuring it

- `just qa <suite> kind=noclick` runs bench cases with all X input refused. A case that passes
  needs no click.
- `just click-census` tallies every click or Escape the turn loop made or tried, from its logs.
- `just click-coverage` fails until every click kind the census has seen has a bench case that
  passed with every click refused.

Forcing tools (the bench creates each situation on demand):

- `M.qa.force_offer(faction, "wife" | "suitor")` opens a marriage or suitor offer with no roll.
- `games/qa/forced.toml`: plague, flood, earthquake, the leader's death, jihad, crusade, a spy report, an AI
  attack, an AI siege, a captured town, men captured.
- `M.qa.parley` opens the diplomacy screen.
- `games/qa/popups.toml`: the papal election cases.

## Still open

- **Forcing an AI diplomatic offer.** Answering one works, but there is no EOP way to make an AI
  faction propose on demand, so the bench can't test it at will.
- **Forcing an adoption offer.** EOP has no adoption twin of `createMessageMarriageProposal`.
- **Upstream.** The fork's bindings (`readBytes`, `getRootUiElements`, `activate()`) would let
  upstream EOP builds play with no clicks too. Fixes to EOP itself belong upstream, in the M2TWEOP
  project.

## How to start

1. Clone the repository and run `just --list`.
2. Read the newest spec in `docs/superpowers/specs/`.
3. Run `just qa smoke kind=noclick`.
4. Pick an open item. Write the noclick bench case first, then the fix.
