import json
import asyncio
from pathlib import Path

import ai_services
from editing_intelligence import (
    context_as_prompt,
    evaluate_edit_plan,
    infer_profile,
    load_knowledge,
    quality_gate_edit_plan,
    retrieve_editing_context,
)


FIXTURE = Path(__file__).resolve().parents[2] / "training" / "fixtures" / "minecraft_plan_quality_cases.json"


def _case():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["words"] = [
        {"word": word, "start": index * 0.25, "end": index * 0.25 + 0.2}
        for index, word in enumerate(data["words"])
    ]
    return data


def test_knowledge_pack_is_valid_and_traceable():
    knowledge = load_knowledge()
    ids = [rule["id"] for rule in knowledge["rules"]]
    assert len(ids) == len(set(ids))
    assert "asset-generated-scope" in ids
    assert knowledge["provenance_policy"]["disallowed"]


def test_profile_inference_and_retrieval_select_minecraft_rules():
    case = _case()
    assert infer_profile(case["words"]) == "minecraft_narrative"
    context = retrieve_editing_context(case["words"], max_rules=20)
    assert context["profile"] == "minecraft_narrative"
    assert "minecraft-native-proof" in context["rule_ids"]
    prompt = context_as_prompt(context)
    assert "Generated graphics are explanatory" in prompt
    assert "fake gameplay" in prompt


def test_grounded_plan_passes_quality_gate():
    case = _case()
    result = quality_gate_edit_plan(case["good_plan"], case["words"], "minecraft_narrative")
    review = result["quality_review"]
    assert review["passed"] is True
    assert review["score"] >= review["threshold"]
    assert result["asset_requests"][0]["provenance"] == "generated_editorial_graphic"
    assert result["asset_requests"][0]["is_evidence"] is False


def test_unsafe_plan_is_repaired_without_inventing_beats():
    case = _case()
    before = evaluate_edit_plan(case["unsafe_plan"], case["words"], "minecraft_narrative")
    result = quality_gate_edit_plan(case["unsafe_plan"], case["words"], "minecraft_narrative")
    assert before["passed"] is False
    assert result["asset_requests"] == []
    assert 999 not in result["filler_indices"]
    assert len(result["emphasis_indices"]) == 15
    assert [beat["beat_type"] for beat in result["story_beats"]] == ["setup", "hook"]
    assert "payoff" not in [beat["beat_type"] for beat in result["story_beats"]]
    assert result["quality_review"]["passed"] is False
    assert any(issue["code"] == "unresolved_hook" for issue in result["quality_review"]["remaining_issues"])


def test_failed_first_plan_gets_one_grounded_semantic_revision(monkeypatch):
    case = _case()
    failed_first = {
        "filler_indices": [], "emphasis_indices": [2, 5], "broll_moments": [],
        "story_beats": [{"word_index": 0, "beat_type": "hook", "intent": "One more loss means a ban"}],
        "transitions": [], "audio_cues": [], "asset_requests": [],
        "pacing_summary": "Fast opening", "title": "One Heart Left", "summary": "A risky search"
    }
    responses = [json.dumps(failed_first), json.dumps(case["good_plan"])]
    prompts = []

    async def fake_call(prompt, keys, system="", want_json=False):
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr(ai_services, "call_text_llm", fake_call)
    result = asyncio.run(ai_services.analyze_transcript(case["words"], {"groq": "test"}, "minecraft_narrative"))

    review = result["quality_review"]
    assert len(prompts) == 2
    assert review["llm_attempt_count"] == 2
    assert review["selected_attempt"] == 2
    assert review["passed"] is True
    assert review["final_score"] == review["score"]
    revision_payload = json.loads(prompts[1])
    assert any(issue["code"] == "unresolved_hook" for issue in revision_payload["evaluation_issues"])
    assert revision_payload["retrieved_rules"]
    assert "0:If" in revision_payload["numbered_transcript"]
    assert "quality_review" not in revision_payload["current_sanitized_plan"]


def test_passing_first_plan_does_not_spend_second_llm_call(monkeypatch):
    case = _case()
    calls = 0

    async def fake_call(prompt, keys, system="", want_json=False):
        nonlocal calls
        calls += 1
        return json.dumps(case["good_plan"])

    monkeypatch.setattr(ai_services, "call_text_llm", fake_call)
    result = asyncio.run(ai_services.analyze_transcript(case["words"], {"groq": "test"}, "minecraft_narrative"))

    assert calls == 1
    assert result["quality_review"]["passed"] is True
    assert result["quality_review"]["llm_attempt_count"] == 1
    assert result["quality_review"]["revision_attempted"] is False


def test_worse_semantic_revision_is_rejected(monkeypatch):
    case = _case()
    safer_first = {
        "filler_indices": [], "emphasis_indices": [2, 5], "broll_moments": [],
        "story_beats": [{"word_index": 0, "beat_type": "hook", "intent": "One more loss means a ban"}],
        "transitions": [], "audio_cues": [], "asset_requests": [],
        "pacing_summary": "Fast opening", "title": "One Heart Left", "summary": "A risky search"
    }
    worse_revision = {
        "filler_indices": [999], "emphasis_indices": [],
        "broll_moments": [{"word_index": 16, "query": "mace", "reason": "decoration", "visual_intent": ""}],
        "story_beats": [
            {"word_index": 40, "beat_type": "hook", "intent": "Unsupported late hook"},
            {"word_index": 12, "beat_type": "setup", "intent": "Out of order"}
        ],
        "transitions": [], "audio_cues": [],
        "asset_requests": [
            {"word_index": 16, "kind": "item_callout", "text": "OFFICIAL PROOF", "subtext": "fake gameplay screenshot", "accent": "red", "reason": "evidence"}
        ],
        "title": "Worse", "summary": "Worse"
    }
    responses = [json.dumps(safer_first), json.dumps(worse_revision)]

    async def fake_call(prompt, keys, system="", want_json=False):
        return responses.pop(0)

    monkeypatch.setattr(ai_services, "call_text_llm", fake_call)
    result = asyncio.run(ai_services.analyze_transcript(case["words"], {"groq": "test"}, "minecraft_narrative"))

    review = result["quality_review"]
    assert review["llm_attempt_count"] == 2
    assert review["selected_attempt"] == 1
    assert review["passed"] is False
    assert len(review["candidate_scores"]) == 2
    assert review["candidate_scores"][0]["score"] > review["candidate_scores"][1]["score"]
    assert result["title"] == "One Heart Left"
