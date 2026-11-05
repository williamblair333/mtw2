from parley.deciders.adoption import DECLINE_BASELINE, AdoptionScore, score_adoption
from parley.protocol import Person


def test_strong_young_candidate_beats_baseline(venice_report):
    candidate = {
        "name": "Bartolomeo",
        "age": 25,
        "command": 5,
        "loyalty": 4,
        "piety": 3,
        "chivalry_or_dread": 2,
        "traits": ["Promising Commander"],
    }
    score = score_adoption(candidate, venice_report)
    assert score.accept > score.decline
    assert score.decline == DECLINE_BASELINE


def test_weak_old_candidate_does_not_beat_baseline(venice_report):
    report = venice_report.model_copy(
        update={
            "family": [
                Person(name="Doge Enrico", role="leader", kind="general", alive=True, family=True),
                Person(name="Angelo", role="heir", kind="general", alive=True, family=True),
            ]
        }
    )
    candidate = {
        "name": "Old Cripple",
        "age": 65,
        "command": 0,
        "loyalty": 2,
        "piety": 0,
        "chivalry_or_dread": 0,
        "traits": [],
    }
    score = score_adoption(candidate, report)
    # Base: 2*0 + 1.5*2 = 3.0. Age > 60: -2.0 -> 1.0. Generals (2 >= 1) and heir present.
    assert score.accept <= score.decline


def test_disloyalty_overrides_command(venice_report):
    report = venice_report.model_copy(
        update={
            "family": [
                Person(name="Doge Enrico", role="leader", kind="general", alive=True, family=True),
                Person(name="Angelo", role="heir", kind="general", alive=True, family=True),
            ]
        }
    )
    candidate_disloyal = {
        "name": "Rebel Heart",
        "age": 50,
        "command": 4,
        "loyalty": 1,
        "piety": 0,
        "chivalry_or_dread": 0,
    }
    candidate_loyal = {
        "name": "True Heart",
        "age": 50,
        "command": 4,
        "loyalty": 2,
        "piety": 0,
        "chivalry_or_dread": 0,
    }
    score_disloyal = score_adoption(candidate_disloyal, report)
    score_loyal = score_adoption(candidate_loyal, report)
    # Loyal: 2*4 + 1.5*2 = 11.0 > 6.0
    # Disloyal: 2*4 + 1.5*1 - 4 = 5.5 <= 6.0
    assert score_loyal.accept > score_loyal.decline
    assert score_disloyal.accept <= score_disloyal.decline
    assert score_loyal.accept - score_disloyal.accept == (1.5 * 2) - (1.5 * 1 - 4)


def test_need_for_generals_raises_accept(venice_report):
    candidate = {"name": "Candidate", "age": 35, "command": 3, "loyalty": 3}
    report_short_with_heir = venice_report.model_copy(
        update={"family": [Person(name="Angelo", role="heir", alive=True, family=True)]}
    )
    report_full_with_heir = venice_report.model_copy(
        update={
            "family": [
                Person(name="Angelo", role="heir", kind="general", alive=True, family=True),
                Person(name="Doge Enrico", role="leader", kind="general", alive=True, family=True),
            ]
        }
    )
    score_short = score_adoption(candidate, report_short_with_heir)
    score_full = score_adoption(candidate, report_full_with_heir)
    assert score_short.accept == score_full.accept + 2.0


def test_no_heir_sets_stakes_to_high(venice_report):
    candidate = {"name": "Candidate", "age": 28, "command": 3, "loyalty": 3}
    report_no_heir = venice_report.model_copy(
        update={"family": [Person(name="Doge Enrico", role="leader", kind="general", alive=True, family=True)]}
    )
    score_no_heir = score_adoption(candidate, report_no_heir)
    assert score_no_heir.stakes == 0.8

    report_with_heir = venice_report.model_copy(
        update={
            "family": [
                Person(name="Doge Enrico", role="leader", kind="general", alive=True, family=True),
                Person(name="Angelo", role="heir", kind="general", alive=True, family=True),
            ]
        }
    )
    score_with_heir = score_adoption(candidate, report_with_heir)
    assert score_with_heir.stakes == 0.3


def test_unknown_command_gives_known_false(venice_report):
    candidate_unknown_cmd = {"name": "Mystery", "age": 25, "command": None, "loyalty": 4}
    score1 = score_adoption(candidate_unknown_cmd, venice_report)
    assert score1.known is False

    candidate_unknown_loy = {"name": "Mystery", "age": 25, "command": 3, "loyalty": None}
    score2 = score_adoption(candidate_unknown_loy, venice_report)
    assert score2.known is False

    candidate_known = {"name": "Clear", "age": 25, "command": 3, "loyalty": 4}
    score3 = score_adoption(candidate_known, venice_report)
    assert score3.known is True


def test_report_none_works():
    candidate = {
        "name": "Solitary",
        "age": 25,
        "command": 4,
        "loyalty": 3,
        "piety": 2,
        "chivalry_or_dread": 1,
    }
    score = score_adoption(candidate, None)
    assert isinstance(score, AdoptionScore)
    # accept = 2*4 + 1.5*3 + 0.5*2 + 0.5*1 + 2 = 8 + 4.5 + 1.0 + 0.5 + 2 = 16.0
    assert score.accept == 16.0
    assert score.decline == DECLINE_BASELINE
    assert score.stakes == 0.3
    assert score.known is True
    assert score.reason == "Command 4, loyalty 3, age 25."


def test_large_family_penalty(venice_report):
    candidate = {"name": "Candidate", "age": 35, "command": 3, "loyalty": 3}
    family_12 = [Person(name=f"Member {i}", alive=True, family=True) for i in range(12)]
    report_12 = venice_report.model_copy(update={"family": family_12})
    family_11 = [Person(name=f"Member {i}", alive=True, family=True) for i in range(11)]
    report_11 = venice_report.model_copy(update={"family": family_11})

    score_12 = score_adoption(candidate, report_12)
    score_11 = score_adoption(candidate, report_11)
    assert score_12.accept == score_11.accept - 2.0


def test_only_the_family_counts_not_every_character_on_record(venice_report):
    # report.family lists agents and others too (Person.family False); they're not kin
    candidate = {"name": "Candidate", "age": 35, "command": 3, "loyalty": 3}
    kin = [Person(name="Angelo", role="heir", kind="general", alive=True, family=True)]
    others = [Person(name=f"Spy {i}", kind="spy", alive=True) for i in range(15)]
    with_others = score_adoption(candidate, venice_report.model_copy(update={"family": kin + others}))
    kin_only = score_adoption(candidate, venice_report.model_copy(update={"family": kin}))
    assert with_others.accept == kin_only.accept and with_others.stakes == 0.3


def test_reason_sentence(venice_report):
    candidate = {"name": "Marco", "age": 24, "command": 4, "loyalty": 3}
    score = score_adoption(candidate, venice_report)
    assert score.reason.startswith("Command 4, loyalty 3, age 24")
    assert score.reason.endswith(".")
    assert score.reason.count(".") == 1
