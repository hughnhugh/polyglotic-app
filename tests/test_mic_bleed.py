"""Mic bleed by loudness (platform.mic_bleed), on synthetic speech-like audio.

Ported from the proof of concept's test_mic_bleed.py (`master-polyglotic`),
the audio half: bursts of syllable-length noise stand in for speech; the
PC's audio leaks into the mic quietly and late, with clicks and taps, or
the user talks over it. (The text half - a "You" caption repeating someone
else's - is the server's, project S2.)
"""

import sys

import numpy as np
import pytest

from polyglotic_desktop.platform.audio_buffer import AudioBuffer
from polyglotic_desktop.platform.mic_bleed import MicBleed, log_line, survey
from polyglotic_desktop.platform.speech_detection import Audio

SR = 16000
T0 = 1000.0
SECONDS = 6


def speech(seed: int) -> Audio:
    """Syllable-like bursts: 120-320ms of shaped noise with short gaps."""
    rng = np.random.default_rng(seed)
    audio = np.zeros(SR * SECONDS)
    t = 0.0
    while t < SECONDS - 0.4:
        length = rng.uniform(0.12, 0.32)
        start, n = int(t * SR), int(length * SR)
        audio[start : start + n] += rng.normal(0, 0.25, n) * np.hanning(n)
        t += length + rng.uniform(0.04, 0.25)
    return audio.astype(np.float32)


def buffer(audio: Audio) -> AudioBuffer:
    out, chunk = AudioBuffer(), 1024
    for i in range(0, len(audio) - chunk + 1, chunk):
        out.append(T0 + i / SR, audio[i : i + chunk].astype(np.float32))
    return out


def late(audio: Audio, ms: int) -> Audio:
    return np.concatenate([np.zeros(int(SR * ms / 1000), dtype=np.float32), audio])[
        : len(audio)
    ]


RNG = np.random.default_rng(7)
THEM, ME = speech(1), speech(2)
NOISE = RNG.normal(0, 0.002, SR * SECONDS).astype(np.float32)
TAPS = np.zeros(SR * SECONDS, dtype=np.float32)
for _ in range(8):
    _start = int(RNG.uniform(0, SECONDS - 0.2) * SR)
    TAPS[_start : _start + 400] += RNG.normal(0, 0.25, 400).astype(np.float32)
_t = np.arange(SR * SECONDS)
HUM = (
    0.2 * np.sin(_t * 2 * np.pi * 220 / SR) * (1 + np.sin(_t * 2 * np.pi * 0.5 / SR))
).astype(np.float32)
SILENT = np.zeros(SR * SECONDS, dtype=np.float32)

CASES = [
    (
        "their voice leaking in, quiet and 120ms late",
        THEM,
        0.04 * late(THEM, 120) + NOISE,
        True,
    ),
    (
        "leaking in, with clicks and taps on the mic",
        THEM,
        0.04 * late(THEM, 150) + 0.6 * TAPS + NOISE,
        True,
    ),
    ("leaking in loud", THEM, 0.15 * late(THEM, 80) + NOISE, True),
    ("me talking over them", THEM, 0.5 * ME + 0.04 * late(THEM, 120) + NOISE, False),
    ("me talking, the PC silent", SILENT, 0.5 * ME + NOISE, False),
    ("me talking over music", HUM, 0.5 * ME + 0.03 * late(HUM, 100) + NOISE, False),
]


@pytest.mark.parametrize(
    ("played", "mic", "expected"), [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_bleed(played: Audio, mic: Audio, expected: bool) -> None:
    check = MicBleed(mic=buffer(mic), played=buffer(played))
    assert check(T0 + 0.5, T0 + 5.5) is expected


LATE_CASES = [
    # polyglotic-hq 290: Bluetooth speakers (typically 0.1-0.3s on their
    # own) and a wireless mic put the mic past the 0.5s it was compared at
    (
        "leaking in from Bluetooth speakers, 0.8s late",
        THEM,
        0.04 * late(THEM, 800) + NOISE,
        True,
    ),
    (
        "me talking over them, 0.8s late",
        THEM,
        0.5 * ME + 0.04 * late(THEM, 800) + NOISE,
        False,
    ),
    # a loopback at a low volume slider, the speakers turned up (decision 0082)
    (
        "leaking in, the PC's loopback quiet",
        0.01 * THEM,
        0.04 * late(THEM, 150) + NOISE,
        True,
    ),
    ("me talking, the PC's loopback quiet", 0.01 * THEM, 0.5 * ME + NOISE, False),
]


@pytest.mark.parametrize(
    ("played", "mic", "expected"),
    [c[1:] for c in LATE_CASES],
    ids=[c[0] for c in LATE_CASES],
)
def test_bleed_late_or_from_a_quiet_loopback(
    played: Audio, mic: Audio, expected: bool
) -> None:
    """From 1.5s in, so the whole lag range has audio before it."""
    check = MicBleed(mic=buffer(mic), played=buffer(played))
    assert check(T0 + 1.5, T0 + 5.5) is expected


def test_too_short_to_tell() -> None:
    check = MicBleed(mic=buffer(0.04 * late(THEM, 120) + NOISE), played=buffer(THEM))
    assert check(T0 + 1.0, T0 + 1.3) is False


def test_nothing_played_yet() -> None:
    check = MicBleed(mic=buffer(0.5 * ME), played=AudioBuffer())
    assert check(T0 + 0.5, T0 + 5.5) is False


def test_the_check_says_how_late_the_mic_was_and_keeps_its_numbers() -> None:
    """polyglotic-hq 290: the check's numbers for the caption log - the
    best correlation, the lag it was found at, whether what played was
    silent - kept until taken; a stretch too short to compare isn't kept."""
    check = MicBleed(mic=buffer(0.04 * late(THEM, 800) + NOISE), played=buffer(THEM))
    assert check(T0 + 1.5, T0 + 5.5) is True
    assert check(T0 + 1.0, T0 + 1.3) is False  # too short: not compared
    [checked] = check.checked()
    assert checked.seconds == pytest.approx(4.0)
    assert checked.found.lag == pytest.approx(0.8, abs=0.04)
    assert checked.found.correlation is not None and checked.found.correlation > 0.6
    assert check.checked() == []  # taken
    line = log_line(checked, 2)
    assert line.startswith("mic bleed_check seconds=4.00 correlation=0.")
    assert "lag_ms=8" in line and line.endswith(
        "played=sound outputs_playing=2 bleed=yes"
    )
    silent = MicBleed(mic=buffer(0.5 * ME), played=buffer(SILENT))
    assert silent(T0 + 1.5, T0 + 5.5) is False
    [nothing] = silent.checked()
    assert (
        log_line(nothing, None) == "mic bleed_check seconds=4.00 played=silent bleed=no"
    )


def test_the_survey_finds_the_speakers_lag_even_past_the_checks() -> None:
    """The harness's `bleed` (polyglotic-hq 290): every 3s of the mic, a
    stretch a second - how often the check calls it bleed, and how late the
    speakers reach the mic, looked for up to 2s."""
    near = survey(buffer(0.04 * late(THEM, 300) + NOISE), buffer(THEM), T0 + 1, T0 + 6)
    assert near.stretches == 3 and near.caught == 3
    assert near.lag == pytest.approx(0.3, abs=0.04)
    far = survey(buffer(0.04 * late(THEM, 1500) + NOISE), buffer(THEM), T0 + 2, T0 + 6)
    assert far.lag == pytest.approx(1.5, abs=0.04) and far.best is not None
    assert far.best > 0.6
    quiet = survey(buffer(0.5 * ME), buffer(SILENT), T0 + 1, T0 + 6)
    assert quiet.played_silent == 3 and quiet.caught == 0 and quiet.played_db < -100


@pytest.mark.skipif(sys.platform != "win32", reason="the harness is Windows'")
def test_the_harness_says_what_the_numbers_mean() -> None:
    """`harness bleed` prints numbers, then one line saying what they mean -
    the speakers past the check's lag, above all (decision 0082)."""
    from polyglotic_desktop.harness import bleed_lines

    far = survey(buffer(0.04 * late(THEM, 1500) + NOISE), buffer(THEM), T0 + 2, T0 + 6)
    said = bleed_lines(far, 1)
    assert "outputs playing: 1" in said
    assert said[-1] == "The speakers reach the mic 1.50s late, past the check's 1.0s."
    near = survey(buffer(0.04 * late(THEM, 300) + NOISE), buffer(THEM), T0 + 1, T0 + 6)
    assert bleed_lines(near, 1)[-1] == "The check catches the speakers in the mic here."
    silent = survey(buffer(0.5 * ME), buffer(SILENT), T0 + 1, T0 + 6)
    assert bleed_lines(silent, 2)[-1].startswith("Windows' default output played next")
