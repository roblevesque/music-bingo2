"""Sound effects the host can trigger from the console. Pure Python.

Today there are three built-in effects (see scripts/generate_effects.py). The console builds its
buttons from whatever list this returns, so offering a choice of effects later means changing
where `available_effects` gets its list (for example, adding the host's uploaded files), not the page.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Effect:
    id: str
    label: str
    file: str  # under app/static/
    loop: bool = False  # a looping effect plays until the host stops it


BUILTIN_EFFECTS: tuple[Effect, ...] = (
    Effect("thinking", "Thinking", "effects/thinking.wav", loop=True),  # while a claim is being checked
    Effect("win", "Win", "effects/win.wav"),
    Effect("lose", "Lose", "effects/lose.wav"),
)


def available_effects(owner_id: int | None = None) -> list[dict]:
    """The effects offered to this host, in the order of their number-key shortcuts.

    `owner_id` is unused for now; it is where per-host effects would be added.
    """
    return [{"id": e.id, "label": e.label, "url": f"/static/{e.file}", "loop": e.loop} for e in BUILTIN_EFFECTS]
