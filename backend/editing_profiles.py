"""Editorial profiles used to steer the analysis pass before rendering."""

MINECRAFT_NARRATIVE = """
MINECRAFT NARRATIVE EDITING PROFILE:
- Open with the single clearest stake, threat, or impossible goal in the first 2 seconds.
- Use quick visual changes only when the story state changes: a new player, danger, a resource milestone, a betrayal, or a payoff. Do not cut randomly.
- Emphasize stakes, player names, item names, numbers, wins, losses, and reveal words. Keep ordinary connective speech visually quiet.
- Suggest B-roll for Minecraft-native proof: inventory/item closeups, map reveals, player/location labels, health/heart changes, crafting, and before/after comparisons.
- Prefer a sequence of: claim -> evidence -> escalation -> setback -> payoff. Give each section one readable on-screen visual.
- Captions should be short, white, centered low, with only the key word highlighted. Avoid captioning every filler or covering essential HUD information.
- For an important transition, prefer an in-world match cut, item wipe, map push, inventory pop, or a purpose-built text/card graphic over a generic effect.
- Never invent a fake gameplay outcome. If an asset is unavailable, request a simple title card, stat card, map label, or item callout instead of unrelated stock footage.
""".strip()


def profile_prompt(name: str | None) -> str:
    return MINECRAFT_NARRATIVE if name == "minecraft_narrative" else ""
