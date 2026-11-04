from __future__ import annotations

from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.questions_read import tool


def test_the_open_questions_are_listed_short():
    out, _ = run_example("questions_read")
    assert out.total == 1 and out.questions == [{"scope": "episode 1", "title": "Who is the caller?"}]


def test_detailed_adds_the_question_and_an_answered_one_is_not_listed():
    case = example_of("questions_read")
    case["fixtures"]["questions"].append({"id": "q2", "production_id": case["production_id"], "key": "k2",
                                          "scope": "scene 2", "title": "Done", "body": "b", "status": "answered"})
    out = tool.run(tool.Args(response_format="detailed"), example_ctx(case))
    assert [q["title"] for q in out.questions] == ["Who is the caller?"]
    assert out.questions[0]["question"].startswith("The script says")


def test_a_long_list_is_paged():
    case = example_of("questions_read")
    case["fixtures"]["questions"] = [{"id": f"q{n}", "production_id": case["production_id"], "key": f"k{n}",
                                      "scope": "s", "title": f"T{n}", "body": "b", "status": "open"}
                                     for n in range(12)]
    first = tool.run(tool.Args(page_size=5), example_ctx(case))
    assert len(first.questions) == 5 and first.total == 12 and first.next_page == 2
