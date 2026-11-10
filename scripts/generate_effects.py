"""Generate the built-in sound effects (win, lose, thinking) as small WAV files.

    uv run python scripts/generate_effects.py            # writes app/static/effects/*.wav

The sounds are synthesised from scratch (sine harmonics, envelopes), so they are original, tiny and
free of licensing questions. Tweak the notes below and rerun to change them. Standard library only.
"""

import math
import struct
import wave
from pathlib import Path

RATE = 22050  # plenty for simple tones, and keeps the files small
PEAK = 0.85  # leave headroom so nothing clips
OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "effects"


def note(freq, dur, *, attack=0.01, tau=0.3, harmonics=(1.0,), release=0.05, vibrato=(0.0, 0.0), glide_to=None):
    """One tone: summed harmonics, a short attack, an exponential decay, and a fade-out at the end."""
    out, phase = [], 0.0
    vib_hz, vib_depth = vibrato
    for i in range(int(RATE * dur)):
        t = i / RATE
        f = freq if glide_to is None else freq + (glide_to - freq) * t / dur
        if vib_hz:
            f *= 1 + vib_depth * math.sin(2 * math.pi * vib_hz * t)
        phase += 2 * math.pi * f / RATE
        tone = sum(amp * math.sin(h * phase) for h, amp in enumerate(harmonics, start=1))
        envelope = min(1.0, t / attack) * math.exp(-t / tau)
        fade = min(1.0, (dur - t) / release) if release else 1.0
        out.append(tone * envelope * fade)
    return out


def tick(freq, dur=0.03):
    """A short clock-like click."""
    return [math.sin(2 * math.pi * freq * i / RATE) * math.exp(-(i / RATE) / 0.006) for i in range(int(RATE * dur))]


def mix(buffer, start, samples, gain=1.0, wrap=False):
    """Add `samples` into `buffer` at `start` seconds. With wrap, the tail wraps round to the start (for loops)."""
    size, offset = len(buffer), int(start * RATE)
    for i, value in enumerate(samples):
        j = offset + i
        if j >= size:
            if not wrap:
                break
            j %= size
        buffer[j] += value * gain


def write_wav(path, buffer):
    peak = max(abs(v) for v in buffer) or 1.0
    scale = PEAK / peak
    frames = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v * scale)) * 32767)) for v in buffer)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(frames)


def win():
    """A rising arpeggio that lands on a bright, ringing chord."""
    buf = [0.0] * int(RATE * 2.6)
    bell = (1.0, 0.35, 0.15)
    for start, freq in ((0.00, 523.25), (0.10, 659.25), (0.20, 783.99)):
        mix(buf, start, note(freq, 0.9, attack=0.005, tau=0.35, harmonics=bell))
    mix(buf, 0.30, note(1046.50, 2.2, attack=0.005, tau=0.8, harmonics=bell), 1.1)
    for freq in (523.25, 659.25, 783.99):
        mix(buf, 0.35, note(freq, 2.0, attack=0.01, tau=0.9, harmonics=bell), 0.45)
    return buf


def lose():
    """'Wah, wah, wah, waaah': four falling brassy notes, the last one sagging and wobbling."""
    buf = [0.0] * int(RATE * 2.9)
    brass = (1.0, 0.5, 0.33, 0.25, 0.2, 0.12)
    for start, freq in ((0.00, 392.00), (0.45, 369.99), (0.90, 349.23)):
        mix(buf, start, note(freq, 0.42, attack=0.04, tau=0.6, harmonics=brass, release=0.08))
    mix(buf, 1.35, note(329.63, 1.5, attack=0.05, tau=1.6, harmonics=brass, release=0.25, vibrato=(5.5, 0.015), glide_to=293.66))
    return buf


def thinking():
    """An 8-second loop: a soft ticking clock over a slowly pulsing low drone and a plucked, tense pattern."""
    seconds, beat = 8.0, 0.5
    size = int(RATE * seconds)
    buf = [0.0] * size
    for i in range(size):  # whole numbers of cycles in the loop, so it joins up without a click
        t = i / RATE
        buf[i] += (0.9 + 0.1 * math.sin(2 * math.pi * t / 4.0)) * (math.sin(2 * math.pi * 110 * t) + 0.3 * math.sin(2 * math.pi * 220 * t)) * 0.16
    pluck = (1.0, 0.4, 0.1)
    melody = [220.00, 329.63, 261.63, 329.63, 220.00, 329.63, 261.63, 392.00,
              233.08, 349.23, 293.66, 349.23, 220.00, 329.63, 246.94, 329.63]  # A minor, with a Bb for tension
    for step, freq in enumerate(melody):
        mix(buf, step * beat, note(freq, 0.6, attack=0.003, tau=0.16, harmonics=pluck, release=0.1), 0.55, wrap=True)
        mix(buf, step * beat, tick(2300 if step % 2 == 0 else 1500), 0.22, wrap=True)  # tick, tock
    return buf


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, make in (("win", win), ("lose", lose), ("thinking", thinking)):
        write_wav(OUT / f"{name}.wav", make())
        print("wrote", OUT / f"{name}.wav")
