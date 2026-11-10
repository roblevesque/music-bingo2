import importlib.util
import wave
from pathlib import Path

import pytest

from app.services.effects import BUILTIN_EFFECTS, available_effects

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"


def read_wav(path):
    with wave.open(str(path)) as handle:
        assert (handle.getnchannels(), handle.getsampwidth()) == (1, 2)  # mono, 16-bit
        frames = handle.readframes(handle.getnframes())
        rate = handle.getframerate()
    samples = [int.from_bytes(frames[i:i + 2], "little", signed=True) / 32768 for i in range(0, len(frames), 2)]
    return samples, rate


def test_the_registry_is_sensible():
    effects = available_effects()
    assert [e["id"] for e in effects] == ["thinking", "win", "lose"]  # the order of the number-key shortcuts
    assert len({e["id"] for e in effects}) == len(effects)
    assert all(e["label"] and e["url"].startswith("/static/effects/") and e["url"].endswith(".wav") for e in effects)
    assert [e["id"] for e in effects if e["loop"]] == ["thinking"]  # only "thinking" runs until stopped


@pytest.mark.parametrize("effect", BUILTIN_EFFECTS, ids=lambda e: e.id)
def test_each_built_in_effect_is_a_usable_audio_file(effect):
    path = STATIC / effect.file
    assert path.is_file(), f"{effect.file} is missing: run scripts/generate_effects.py"
    samples, rate = read_wav(path)
    seconds = len(samples) / rate
    assert (4 <= seconds <= 16) if effect.loop else (1 <= seconds <= 4)
    peak = max(abs(s) for s in samples)
    assert 0.5 <= peak <= 0.9  # loud enough to be useful, with headroom against clipping
    assert sum(s * s for s in samples) / len(samples) > 0.002  # not silence
    assert path.stat().st_size < 600_000  # small enough to ship in the repository


def test_the_thinking_loop_joins_up_without_a_click():
    samples, _ = read_wav(STATIC / "effects" / "thinking.wav")
    seam = abs(samples[0] - samples[-1])
    typical = sum(abs(a - b) for a, b in zip(samples, samples[1:])) / (len(samples) - 1)
    assert seam < typical * 2


def test_the_committed_files_match_the_generator(tmp_path):
    spec = importlib.util.spec_from_file_location("generate_effects", ROOT / "scripts" / "generate_effects.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, make in (("win", module.win), ("lose", module.lose), ("thinking", module.thinking)):
        fresh = tmp_path / f"{name}.wav"
        module.write_wav(fresh, make())
        assert fresh.read_bytes() == (STATIC / "effects" / f"{name}.wav").read_bytes(), f"{name}.wav is out of date"
