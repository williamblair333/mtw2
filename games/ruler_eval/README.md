# Ruler eval: the fixed scenario set

Six real turns from run 9 (scratch, 2026-11-05, Heretic rulers on the test laptop), kept so every ruler
model or prompt is scored on the same inputs (STANDARDS ruler-eval-harness). Each folder holds the
turn's `state.json` (the report) and `prompt.txt` (what the ruler was asked), as the turn loop wrote
them.

| folder | faction | turn | why it's here |
| --- | --- | --- | --- |
| run9-76-england | England | 76 | four towns, Scotland pressing the north |
| run9-80-france | France | 80 | five towns, many captains' armies, five orders refused that turn |
| run9-82-england | England | 82 | London just lost to Scotland, three towns left |
| run9-88-france | France | 88 | a large army list, a siege of Metz under way |
| run9-90-england | England | 90 | three towns, low money, war on two fronts |
| run9-94-france | France | 94 | late game, steady state |

Score seats with `just ruler-eval-fixed <seat spec>...` (e.g. `heretic:think agy:gemini-3.8-flash-low`).
For each seat and scenario it records the legal-order rate, whether the seat answered, and the time
(runs/ruler-eval/). Scoring how good the orders are, beyond whether they are legal, is still open.
