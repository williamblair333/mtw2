from parley.events import diff_reports


def _r(report, **update):
    return report.model_copy(update=update)


def test_no_previous_report_no_events(venice_report):
    assert diff_reports(None, venice_report) == []


def test_stance_change(venice_report):
    before = venice_report
    after = _r(venice_report, factions=[f.model_copy(update={"stance": "war"}) if f.id == "milan" else f
                                        for f in venice_report.factions])
    assert diff_reports(before, after) == ["Milan (milan): now at war with you (was peace)."]


def test_settlement_lost_and_gained(venice_report):
    ragusa = venice_report.settlements[1]
    zagreb = ragusa.model_copy(update={"id": "Zagreb", "name": "Zagreb"})
    after = _r(venice_report, settlements=[venice_report.settlements[0], zagreb])
    events = diff_reports(venice_report, after)
    assert "You lost Ragusa." in events and "You gained Zagreb." in events


def test_army_gone_and_treasury(venice_report):
    after = _r(venice_report, armies=[], treasury=venice_report.treasury + 2000)
    events = diff_reports(venice_report, after)
    assert "Your army Doge Enrico is gone (destroyed, disbanded or merged)." in events
    assert "Treasury: 5000 → 7000 (+2000)." in events


def test_small_treasury_change_reported_too(venice_report):
    after = _r(venice_report, treasury=venice_report.treasury - 300)
    assert diff_reports(venice_report, after) == ["Treasury: 5000 → 4700 (-300)."]
