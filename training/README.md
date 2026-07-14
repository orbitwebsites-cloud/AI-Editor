# Klipped editing intelligence

This directory is the reviewable knowledge and evaluation layer for Klipped. It is retrieval-augmented planning, not a claim that public creator videos were used to fine-tune a model.

## Runtime flow

1. Whisper produces word-level transcript timing.
2. `backend/editing_intelligence.py` infers a broad profile such as `minecraft_narrative`, `gaming`, or `talking_head`.
3. It retrieves a small set of original editing principles from `editing_knowledge_v1.json` and supplies their IDs to the planning prompt.
4. The model returns story beats, B-roll intent, transitions, audio cues, emphasis, and optional editorial-graphic requests.
5. A deterministic quality loop checks grounding, story order, payoff, effect density, visual intent, index validity, and generated-asset honesty. It removes unsafe or mechanically invalid decisions without inventing missing footage or story beats.
6. The saved `quality_review` records the selected profile, score, remaining issues, rounds, and rule IDs used.

The quality gate can fail while still returning a safe plan. A failure means the result needs review; it must not be "fixed" by inventing a payoff.

## Generated assets

The permitted fallback is an explicitly generated editorial graphic: title card, stat layout, player label, item callout, quote treatment, diagram, or abstract background. Every generated request is tagged:

```json
{
  "provenance": "generated_editorial_graphic",
  "is_evidence": false
}
```

Generated gameplay, official-looking screenshots, fake results, fake quotes, fake people, or hallucinated logos are rejected. If a real logo is needed, it must come from the user's supplied/licensed library.

## Creator references

`creator_reference_catalog.json` stores public research pointers and questions. It intentionally does not contain copied timelines, downloaded frames, or a "style clone" setting. Observations may be added only when they are written as general editing principles and carry source/provenance notes.

`Danny` remains unresolved until the exact channel is supplied. `Lifesteal SMP ecosystem` remains a category, not a claim about a specific creator.

## Adding knowledge

Add a rule with a unique stable `id`, relevant `tags`, a single actionable `rule`, its `rationale`, an explicit `guardrail`, and a weight from 1 to 10. Prefer principles that can be evaluated from a transcript or owned footage. Do not add instructions to imitate a creator's identity or reproduce an exact sequence.

Run the focused tests from `backend/`:

```powershell
python -m pytest tests\test_editing_intelligence.py -o required_plugins= -o addopts= -q
```

The fixture is synthetic and intentionally includes a good plan and an unsafe plan. Add new synthetic cases for talking-head, general gaming, and future profiles before changing scoring thresholds.
