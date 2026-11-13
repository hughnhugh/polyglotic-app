"""Mic bleed: the PC's own audio picked up by the mic, caught by loudness.

Mic speech whose loudness follows what the PC was playing is the PC's audio
leaking from speakers or headphones into the mic, not the user talking.
Moved from the proof of concept (`overlay_core.is_bleed`, `_envelope`,
`_median5`), pure numpy:
- loudness envelopes in 20ms frames, in log terms;
- a 5-frame running median on the mic takes out clicks and taps;
- a correlation of at least 0.65, with the mic up to 1s behind the PC,
  counts as bleed (decision 0082: Bluetooth speakers and wireless mics can
  put it past the proof of concept's 0.5s; with twice the lags to match
  by chance, 0.65 rather than 0.6 keeps the user's own speech dropped
  below what it was);
- at least 0.4s of audio is needed, and nothing is bleed when the PC was
  nearly silent (under about -66 dBFS: Windows' loopback of an output can
  be at its volume slider's level while the speakers are turned up,
  decision 0082).

What the PC played is the whole system's loopback on the output device,
whatever is being captioned - decision 0004.

**Seen without content** (polyglotic-hq 290): each stretch compared is
kept with its numbers (`BleedMeasure`: the best correlation, the lag it
was found at, whether what played was nearly silent) for the caption
log's line (`log_line`); `survey` runs the check over a few seconds for
the harness's `bleed`, a learner's own 20-second check.
"""

from collections import deque
from dataclasses import dataclass

import numpy as np

from polyglotic_desktop.platform.audio_buffer import AudioBuffer
from polyglotic_desktop.platform.speech_detection import Audio

BLEED_CORRELATION = 0.65  # 0.6 until decision 0082
BLEED_MAX_LAG_SEC = 1.0
"""How far the mic can trail the PC's output: the output device's latency
(Bluetooth's alone is typically 0.1-0.3s) and the mic's. 0.5s until
decision 0082."""
BLEED_MIN_SEC = 0.4
SILENT_PLAYBACK_RMS = 0.0005
"""What the PC played is nearly silent below this loudness (20ms frames,
about -66 dBFS). 0.005 (-46 dBFS) until decision 0082."""
CHECKED_KEPT = 32  # stretches checked, kept until the caption log takes them
_ENVELOPE_FRAME = 320  # 20ms at 16kHz
_FRAME_SEC = 0.02
_SILENT_PLAYBACK = float(np.log(SILENT_PLAYBACK_RMS))


@dataclass(frozen=True, slots=True)
class BleedMeasure:
    """What the check found for one stretch of the mic - numbers only: the
    best correlation of the loudness envelopes (None: not compared), how
    far the mic trailed what played at the best (seconds), and whether
    what played was nearly silent."""

    correlation: float | None
    lag: float | None
    played_silent: bool = False

    @property
    def bleed(self) -> bool:
        return self.correlation is not None and self.correlation >= BLEED_CORRELATION


NOT_COMPARED = BleedMeasure(None, None)
"""Too short to tell, or no audio to compare."""


def _envelope(audio: Audio) -> Audio:
    """Loudness over time, 20ms frames, in log terms - comparable between a
    loud original and a quiet copy of it."""
    n = len(audio) // _ENVELOPE_FRAME
    frames = audio[: n * _ENVELOPE_FRAME].reshape(n, _ENVELOPE_FRAME)
    envelope: Audio = np.log(np.sqrt((frames**2).mean(axis=1)) + 1e-4).astype(
        np.float32
    )
    return envelope


def _median5(values: Audio) -> Audio:
    if len(values) < 5:
        return values
    padded = np.pad(values, 2, mode="edge")
    median: Audio = np.median(
        np.lib.stride_tricks.sliding_window_view(padded, 5), axis=1
    )
    return median


def measure(mic: Audio, played: Audio) -> BleedMeasure:
    """How much `mic`'s loudness moves with what the PC played (`played`,
    ending when `mic` ends and starting earlier - by BLEED_MAX_LAG_SEC in
    the check): the best correlation over each lag of the mic behind the
    PC, and that lag."""
    # A running median over 100ms takes out clicks, taps and bumps on the
    # mic - the light noise that opened the speech segment - while
    # syllables of real speech, a few times longer, come through.
    m, p = _median5(_envelope(mic)), _envelope(played)
    if len(m) < 10 or len(p) < len(m):
        return NOT_COMPARED  # too short to tell
    if p.max() < _SILENT_PLAYBACK:
        return BleedMeasure(None, None, played_silent=True)
    if m.std() < 1e-6:
        return NOT_COMPARED
    best, at = -1.0, 0
    for offset in range(len(p) - len(m) + 1):  # each lag of the mic behind the PC
        window = p[offset : offset + len(m)]
        if window.std() < 1e-6:
            continue
        correlation = float(np.corrcoef(m, window)[0, 1])
        if correlation > best:
            best, at = correlation, offset
    # both end together: the window `at` frames in is the mic's, that far behind
    return BleedMeasure(best, (len(p) - len(m) - at) * _FRAME_SEC, played_silent=False)


def is_bleed(mic: Audio, played: Audio) -> bool:
    """True if `mic` is mostly `played` picked up again: its loudness moves
    with what the PC played, which the user's own voice doesn't. The
    user's voice over someone else's still counts as the user: it
    dominates the mic's loudness, so the two don't move together."""
    return measure(mic, played).bleed


@dataclass(frozen=True, slots=True)
class Checked:
    """One stretch of the mic checked: how long, and what was found."""

    seconds: float
    found: BleedMeasure


def log_line(checked: Checked, outputs_playing: int | None) -> str:
    """The caption log's line for one stretch of the mic checked - numbers
    only: its seconds, the best correlation and its lag, whether what
    played was nearly silent, how many outputs were playing (None: not
    known), and the verdict."""
    found = checked.found
    fields = {
        "seconds": f"{checked.seconds:.2f}",
        "correlation": None
        if found.correlation is None
        else f"{found.correlation:.2f}",
        "lag_ms": None if found.lag is None else round(found.lag * 1000),
        "played": "silent" if found.played_silent else "sound",
        "outputs_playing": outputs_playing,
        "bleed": "yes" if found.bleed else "no",
    }
    said = [f"{name}={value}" for name, value in fields.items() if value is not None]
    return " ".join(["mic bleed_check", *said])


class MicBleed:
    """The mic's bleed check for `core.listening.timing` (the
    `MicBleedCheck` port): the mic's audio against what the PC played.
    Each stretch checked is kept (`checked`) until taken, for the caption
    log: the check runs under the speech pipeline's lock, the log is
    written after it."""

    def __init__(self, mic: AudioBuffer, played: AudioBuffer) -> None:
        self._mic = mic
        self._played = played
        self._checked: deque[Checked] = deque(maxlen=CHECKED_KEPT)

    def __call__(self, start: float, end: float, /) -> bool:
        found = self.measure(start, end)
        if found is not NOT_COMPARED:
            self._checked.append(Checked(end - start, found))
        return found.bleed

    def measure(self, start: float, end: float) -> BleedMeasure:
        """The check's numbers for the mic's audio from `start` to `end`."""
        if end - start < BLEED_MIN_SEC:
            return NOT_COMPARED
        mic = self._mic.slice(start, end)
        played = self._played.slice(start - BLEED_MAX_LAG_SEC, end)
        if mic is None or played is None:
            return NOT_COMPARED
        return measure(mic, played)

    def checked(self) -> list[Checked]:
        """The stretches checked since last asked, oldest first."""
        taken = []
        while self._checked:
            taken.append(self._checked.popleft())
        return taken


SURVEY_STRETCH_SEC = 3.0
SURVEY_STEP_SEC = 1.0
SURVEY_MAX_LAG_SEC = 2.0
"""How late the survey looks for the speakers in the mic: past the check's
own range, to say how far past it they are."""


@dataclass(frozen=True, slots=True)
class BleedSurvey:
    """The bleed check over a few seconds of the mic beside what the PC
    played, in SURVEY_STRETCH_SEC stretches - numbers only (the harness's
    `bleed`, for a learner whose speakers' sound is captioned as theirs).
    Loudness is the loudest 20ms, in dBFS; correlations and lags are the
    stretches' medians (None: none compared)."""

    stretches: int
    played_db: float
    mic_db: float
    played_silent: int
    caught: int
    correlation: float | None
    lag: float | None
    """Where the best match is, the mic up to SURVEY_MAX_LAG_SEC late."""
    best: float | None
    """The best match's correlation."""


def _loudest_db(audio: Audio | None) -> float:
    if audio is None or len(audio) < _ENVELOPE_FRAME:
        return -120.0
    n = len(audio) // _ENVELOPE_FRAME
    rms = np.sqrt((audio[: n * _ENVELOPE_FRAME].reshape(n, -1) ** 2).mean(axis=1))
    return float(20 * np.log10(rms.max() + 1e-6))


def _median(values: list[float]) -> float | None:
    return float(np.median(values)) if values else None


def survey(
    mic: AudioBuffer, played: AudioBuffer, start: float, end: float
) -> BleedSurvey:
    """The check on every SURVEY_STRETCH_SEC of the mic from `start` to
    `end`, a stretch every SURVEY_STEP_SEC; and where the mic best matches
    what played, up to SURVEY_MAX_LAG_SEC late."""
    check = MicBleed(mic, played)
    found: list[BleedMeasure] = []
    wide: list[BleedMeasure] = []
    at = start
    while at + SURVEY_STRETCH_SEC <= end + 1e-9:
        stop = at + SURVEY_STRETCH_SEC
        found.append(check.measure(at, stop))
        heard, sound = mic.slice(at, stop), played.slice(at - SURVEY_MAX_LAG_SEC, stop)
        if heard is not None and sound is not None:
            wide.append(measure(heard, sound))
        at += SURVEY_STEP_SEC
    return BleedSurvey(
        stretches=len(found),
        played_db=_loudest_db(played.slice(start, end, pad=0.0)),
        mic_db=_loudest_db(mic.slice(start, end, pad=0.0)),
        played_silent=sum(f.played_silent for f in found),
        caught=sum(f.bleed for f in found),
        correlation=_median(
            [f.correlation for f in found if f.correlation is not None]
        ),
        lag=_median([w.lag for w in wide if w.lag is not None]),
        best=_median([w.correlation for w in wide if w.correlation is not None]),
    )
