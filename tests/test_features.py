"""Deterministic task scoring: pure, no clock/network/random."""

from scout.features import score_task


def test_deep_keywords_push_deep():
    goal = ("Please review the billing module architecture and document the migration "
            "design decisions for the whole team so everyone understands the plan "
            "across every service and pipeline")
    out = score_task({"goal": goal, "context": ""})
    assert out["class"] == "deep" and out["score"] >= 2
    assert any(s.startswith("deep-keyword:") for s in out["signals"])


def test_quick_keywords_and_short_text_push_quick():
    out = score_task({"goal": "quick lookup of the docs"})
    assert out["class"] == "quick" and out["score"] <= -2


def test_tie_is_default():
    # deep keyword balances quick keyword; neutral-length text → numeric tie → default.
    goal = ("Please review and quickly summarize the platform status overview today "
            "for the standup so the team has a shared update on progress")
    out = score_task({"goal": goal})
    assert out["class"] == "default"


def test_images_push_deep():
    goal = ("Please give these shots a thorough review and tell me what is happening "
            "across the whole product surface so I can spot regressions before the "
            "release goes out this week")
    out = score_task({"goal": goal, "images": ["a.png"]})
    assert out["class"] == "deep"
    assert "images" in out["signals"]


def test_long_text_alone_is_not_deep_and_short_alone_is_not_quick():
    # A single +1/-1 point never crosses the ±2 threshold.
    long_goal = " ".join(["neutral"] * 125)
    assert score_task({"goal": long_goal})["class"] == "default"
    assert score_task({"goal": "hello there"})["class"] == "default"


def test_long_text_plus_keyword_is_deep():
    # word count > 120 contributes the deciding extra point.
    goal = "review " + " ".join(["neutral"] * 125)
    out = score_task({"goal": goal})
    assert out["class"] == "deep"


def test_neutral_task_is_default_with_zero_score():
    goal = " ".join(["neutral"] * 50)
    out = score_task({"goal": goal, "context": ""})
    assert out == {"class": "default", "score": 0, "signals": [out_sign for out_sign in out["signals"]]}
    assert out["class"] == "default"
    assert out["score"] == 0


def test_context_is_scored_too():
    goal = ("Handle the platform status overview for the whole team carefully today "
            "and tomorrow across all of the services and regions in scope")
    context = "This is a full review of the architecture"
    assert score_task({"goal": goal, "context": context})["class"] == "deep"


def test_deterministic():
    task = {"goal": "quick lookup of the docs", "images": ["a.png"]}
    assert score_task(task) == score_task(dict(task))
