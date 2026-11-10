"""The eval script runs end to end against the demo provider and cleans up after itself.

This checks the harness, not quality: the demo provider's scores are not a model evaluation.
"""

from app.models import Document, User
from evals.dataset import DOCS, QUESTIONS
from evals.run import print_report, run, value_matches


def test_value_matching_is_lenient_but_not_loose() -> None:
    assert value_matches("18500", "18,500")
    assert value_matches("Sunita Verma", "Sunita Verma (DEMO)")
    assert value_matches("0.253", "0.253 हेक्टेयर")
    assert not value_matches("18500", "37000")
    assert not value_matches("Arjun Mehta", None)


def test_eval_runs_and_cleans_up(db, capsys) -> None:
    rep = run(db)
    assert rep.is_demo
    assert rep.fields_total == sum(len(d["fields"]) for d in DOCS.values())
    assert rep.answerable + rep.should_refuse == len(QUESTIONS)
    assert len(rep.latencies_ms) == len(QUESTIONS)
    assert db.query(User).count() == 0 and db.query(Document).count() == 0
    print_report(rep)
    assert "NOT a model evaluation" in capsys.readouterr().out
