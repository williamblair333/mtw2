"""A decision press must never land on a papal scroll's vote button.

Live 11-25 09:49:44 (turn 4877, crash report 2026-11-25-095032 on tc): England accepted an adoption
offer; the bridge logged "pressed accept on unnamed by its element" and the game crashed 0.4 s later
at medieval2.exe+0x7f47bc, inside UI::DECIDED_VOTE_BUTTON (the 11-20 08:36 crash's site too). A papal
message had come 28 s earlier. The papal results scroll shows as "unnamed", so K.PAPAL_SCROLLS (by
name) didn't skip it, and choice_buttons finds accept/decline by shape: two square buttons side by
side, which its vote buttons are.
"""
from tests.test_lua_bridge import lua  # noqa: F401  (the fixture)

SCROLL = """
    M2TWEOP.forkLevel = 6
    local function sq(x, vt, name)
        return { elementName = '', xPos = x, yPos = 500, xSize = 42, ySize = 42, subElementsNum = 0,
                 readBytes = vt and function() return vt end or nil,
                 execute = function() FAKE.calls[#FAKE.calls + 1] = 'press ' .. name end }
    end
    function make_scroll(vt_scroll, vt_btn)
        local a, b = sq(466, vt_btn, 'left'), sq(516, vt_btn, 'right')
        local part = { subElementsNum = 2, getSubElement = function(self, i) return i == 0 and a or b end }
        return { elementName = '', subElementsNum = 1,
                 readBytes = vt_scroll and function() return vt_scroll end or nil,
                 getSubElement = function(self, i) return part end }
    end
"""


def test_vote_buttons_are_not_a_decisions_check_and_x(lua):
    lua.execute(SCROLL)
    # the papal results scroll's decided-vote buttons: same shape as an offer's check and X
    assert lua.eval("BRIDGE.choice_buttons(make_scroll('dc4d3901', '1c463901'))") is None
    assert lua.eval("BRIDGE.choice_buttons(make_scroll(nil, '9c3e3901'))") is None
    # an offer's buttons (no papal class) are still found
    assert lua.eval("BRIDGE.choice_buttons(make_scroll(nil, nil)) ~= nil")


def test_an_unnamed_papal_results_scroll_is_not_an_open_choice(lua):
    lua.execute(SCROLL + """
        BRIDGE.open_ui = function()
            return { { name = 'unnamed', el = make_scroll('dc4d3901', nil) },
                     { name = 'unnamed', el = make_scroll(nil, nil) } }
        end
    """)
    assert lua.eval("#BRIDGE.open_choices()") == 1
    assert lua.eval("BRIDGE.ui_class(BRIDGE.open_choices()[1].el)") is None


def test_press_choice_refuses_a_vote_button(lua):
    lua.execute(SCROLL + """
        local s = make_scroll(nil, '1c463901')
        BRIDGE.open_choices = function()
            return { { name = 'unnamed', el = s, accept = s:getSubElement(0):getSubElement(0),
                       decline = s:getSubElement(0):getSubElement(1) } }
        end
    """)
    assert lua.eval("{BRIDGE.press_choice('accept', 'an adoption offer')}")[2] == "vote_button"
    assert not any(c.startswith("press ") for c in lua.eval("FAKE.calls").values())
    log = (lua.root / "parley_bridge.log").read_text()
    assert "not pressed" in log and "DECIDED_VOTE_BUTTON" in log
