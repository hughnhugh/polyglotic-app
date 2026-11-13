"""The one place that wires everything together.

`main` builds the interface (`ui.app.DesktopApp`) on the learner's data
and dictionary, the speech pipeline and its sources from the user's
settings, and the connection to the server (`connection.client.Connection`:
the listening session, and sync sessions for what waits in the outbox),
then connects them:
- **the session's listener calls arrive on the session's own thread**
  (decision 0012): `QtListener` hands caption updates to the caption feed,
  which queues them to the Qt thread, and the session's state to Home
  through a queued signal; the pace hint goes to the pipeline, which is
  thread-safe;
- **the settings**, as they change: the listening settings to the session;
  the source choice (the apps picked, by name, or everything the PC
  plays; the mic) starts and stops the sources that changed; the
  live-update interval and Pause to the timing rules;
- **learning data** (project 028): Learning's events go to the
  `DataExchange` (kept in the outbox until the server has them); statuses
  and saved words from the server - of the learner's dictionary only, for
  an account learning both languages - come back on a session's thread
  and are applied on the Qt thread without being sent back (`QtExchange`);
  finished days' exposure counts are handed over at start and hourly -
  kept only with their consent;
- **hotkeys**: Ctrl+Alt+L, P and H (lock, pause, hide) registered with
  Windows on a thread of their own; each press goes to the interface's
  thread;
- **feedback** (project 053): "Report a problem" and "Suggest something"
  open the form - and, if the app hit an error nothing caught last time
  (`CrashLog` leaves `crashed.json` in the data folder), Home offers once
  to send a report with the log; a report is kept in the data folder's
  `feedback` folder
  first, then sent on a thread of its own (`FeedbackSender`) - again at
  start, after signing in and every 10 minutes while any waits; signing
  out forgets them. What became of it shows on Home.
- **first run** (`first_run`, decisions 0054 and 0085): one run of screens
  before anything is built on their answers, each after the first with
  Back (polyglotic-hq 250) - no language (293: the learner's dictionary
  and learning data are the language learned's, chosen on Learning, or a
  guess from Windows' languages until then; a change applies at the next
  start) and no level (estimated at a middle one until set: Home's line
  asks), the consent screen with its yes to the
  tester agreement; without it the app quits, and new words of the
  agreement ask again at start (polyglotic-hq 185) - then signing in
  with an invite code (later starts signed out ask it over the window);
  the Account page signs in and out, changes what's shared, and deletes
  learning data (here too only if ticked).

- **the interface** (decisions 0031 and 0032): the new main window
  (`Hub`: Home, Words, Account, Settings, Help), a caption window per app
  captioned (at most 3) or one joined window, a transcript per app, and
  today's tray and dialogs. Each window's language - or Original only -
  goes to the server as its source's own (`listening_settings`); the mic
  is captured only while a window shows my speech; only the first 3 apps
  picked are captured. A window's settings popover never has the focus,
  so Esc or a click elsewhere reaches it through Windows' key state
  (`ports.system.KeyState`), read, not taken.

- **the OS** (decision 0038): its adapters - audio, the app list, the
  device token's store, hotkeys, key state, staying on top, the taskbar's
  look, the OS's version, the data folder - picked in one place,
  `os_adapters`, and imported only there; nothing else imports
  `platform.windows` (import-linter's `os-in-one-place`).

- **updates** (decision 0017): the installer's start-up hooks before
  anything else; then a look for an update on a thread of its own, before
  the interface is built, and every few hours; what each look found goes
  to Home, the tray and Settings (`UpdateShown`: a downloaded update
  offered, with Restart now - polyglotic-hq 299); downloaded updates apply at
  the next start; the channel `welcome` names is followed; the server's
  "update required" goes straight to the updater.

    uv run python -m polyglotic_desktop.main --server http://127.0.0.1:8217

It logs to `logs/polyglotic.log` in the data folder (from source, to the
console as well; installed, it has none) - an exception nothing caught
too, by its type and place (`CrashLog`), with a plain box if it stops the
app starting. `--check-install REPORT` builds everything without
showing, capturing or connecting, and writes what it found (the release
build runs it on the packed app). Logs states only - never caption text,
audio or settings.

What the window doesn't need is imported after its first paint (project
108's fix f; polyglotic-hq project 136): the connection (pydantic,
websockets), speech detection (numpy, onnxruntime) and the signed feed's
libraries took about 0.3 s of the 0.55 s of imports from source. Their
names are typed under `TYPE_CHECKING` and imported where first used;
`tests/test_start_imports.py` keeps them out of `import main`.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import logging.handlers
import sys
import tempfile
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import urlsplit

import shiboken6
from PySide6.QtCore import (
    QEvent,
    QLocale,
    QObject,
    Qt,
    QTimer,
    QTranslator,
    Signal,
    Slot,
    qVersion,
)
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QApplication, QWidget

from polyglotic_desktop.adapters.anki_package import GenankiDeckWriter
from polyglotic_desktop.adapters.app_log import read_log
from polyglotic_desktop.adapters.background_learning import BackgroundLearningStore
from polyglotic_desktop.adapters.background_outbox import BackgroundOutbox
from polyglotic_desktop.adapters.feedback_files import FeedbackFolder
from polyglotic_desktop.adapters.japanese_split import JapaneseSplit
from polyglotic_desktop.adapters.json_settings import JsonSettingsStore
from polyglotic_desktop.adapters.problem_report_files import ProblemReportFolder
from polyglotic_desktop.adapters.spaced_split import SpacedSplit
from polyglotic_desktop.adapters.sqlite_dictionary import (
    DictionaryFormatError,
    GuardedDictionary,
    SqliteDictionary,
)
from polyglotic_desktop.adapters.sqlite_learning import (
    SqliteLearningStore,
    open_learning_store,
    read_level_file,
    set_aside_in,
    unreadable_in,
)
from polyglotic_desktop.adapters.sqlite_outbox import open_outbox
from polyglotic_desktop.adapters.velopack_updates import (
    VelopackUpdater,
    run_installer_hooks,
)
from polyglotic_desktop.connection.app import AppInfo, this_release
from polyglotic_desktop.core.learning.languages import (
    FULL,
    learned_code,
    starting_language,
)
from polyglotic_desktop.core.learning.levels import LevelCurve
from polyglotic_desktop.core.learning.lookups import LookupContext
from polyglotic_desktop.core.learning.vocabulary import (
    Changed,
    EntryText,
    Vocabulary,
    VocabularyChanged,
)
from polyglotic_desktop.core.lexicon.basic import BasicDictionary
from polyglotic_desktop.core.lexicon.chinese import ChineseDictionary
from polyglotic_desktop.core.lexicon.english import EnglishDictionary
from polyglotic_desktop.core.lexicon.entries import (
    DEFAULT_CHINESE_SCHEME,
    ENGLISH_FREQUENCY,
)
from polyglotic_desktop.core.lexicon.meanings import short_meaning
from polyglotic_desktop.core.listening.captions import (
    CaptionKind,
    CaptionUpdate,
    Language,
)
from polyglotic_desktop.core.listening.delays import CAPTION_LOG
from polyglotic_desktop.core.listening.display import (
    LinkDetail,
    LinkGap,
    LinkLine,
    WordLinks,
)
from polyglotic_desktop.core.listening.history import Caption
from polyglotic_desktop.core.listening.problem_report import (
    SpeechPart,
    captions_as_shown,
    speech_by_source,
)
from polyglotic_desktop.core.listening.recheck import (
    LineFlagged,
    RecheckOutcome,
    RecheckRequest,
    RecheckResult,
)
from polyglotic_desktop.core.listening.settings import (
    ListeningSettings,
    agreed_language,
)
from polyglotic_desktop.core.listening.sources import (
    DICTATION,
    EVERYTHING_ELSE,
    MIC,
    SAMPLE,
    WHOLE_SYSTEM,
    Capture,
    Source,
    SourceId,
    capture_of,
    known_app_id,
)
from polyglotic_desktop.core.listening.summary import SessionAction
from polyglotic_desktop.core.listening.timing import (
    CaptionMode,
    CaptionTiming,
    Decision,
    TranscriptionRequest,
)
from polyglotic_desktop.core.listening.unreachable import Unreachable
from polyglotic_desktop.core.releases.updates import (
    CHECK_EVERY_HOURS,
    Found,
    RestartOffer,
    UpdateNow,
    Updates,
    whats_new,
)
from polyglotic_desktop.core.shared import EntryFacts, EntryId, LearningEvent, Level
from polyglotic_desktop.perf.watchdog import Watchdog
from polyglotic_desktop.platform.sample import SampleCapture, SoundOut, sample_file
from polyglotic_desktop.ports.capture import (
    AppCaptureSupport,
    AppCaptureTrial,
    AppList,
    AudioCapture,
    CommonApp,
    PlayingApp,
    SourceCategory,
    TrialOutcome,
)
from polyglotic_desktop.ports.consent import Agreement, ConsentChoice
from polyglotic_desktop.ports.credentials import CredentialStore
from polyglotic_desktop.ports.feedback import Report, ReportKind, WaitingReports
from polyglotic_desktop.ports.problem_reports import ProblemReport, ReportedSpeech
from polyglotic_desktop.ports.settings import SettingsStore
from polyglotic_desktop.ports.startup import IN_TRAY, StartWithWindows
from polyglotic_desktop.ports.system import (
    DataFolder,
    ErrorBox,
    ForegroundWatch,
    HoldKey,
    Hotkeys,
    KeyboardWindow,
    KeyState,
    LaunchClock,
    LightTaskbar,
    OnTop,
    OsVersion,
    StorePackage,
    TaskbarIdentity,
    TypeText,
)
from polyglotic_desktop.ports.updates import Update
from polyglotic_desktop.ui import icons, interface_language, theme
from polyglotic_desktop.ui.app import ConnectionState, DesktopApp
from polyglotic_desktop.ui.apps_with_sound import AppsWithSound
from polyglotic_desktop.ui.consent import ConsentDialog, agreement_needed
from polyglotic_desktop.ui.delete_learning import DeleteLearningDialog
from polyglotic_desktop.ui.feedback import FeedbackDialog
from polyglotic_desktop.ui.first_run import BACK, Answer, Step, asked
from polyglotic_desktop.ui.first_run import run as run_first_run
from polyglotic_desktop.ui.learning import LearningTools
from polyglotic_desktop.ui.level_picker import LevelPicker
from polyglotic_desktop.ui.problem_report import (
    OneReportWindow,
    Part,
    ProblemReportDialog,
    captions_detail,
    captions_look,
    mic_name,
    part_labels,
    speech_detail,
    speech_label,
    speech_look,
)
from polyglotic_desktop.ui.settings import (
    MAX_SOURCE_NAME,
    SOURCE_KEY_EVERYTHING_ELSE,
    SOURCE_KEY_MIC,
    SOURCE_KEY_SAMPLE,
    SOURCE_KEY_SYSTEM,
    AppSettings,
    Settings,
    introductions_changes,
    learning_changes,
)
from polyglotic_desktop.ui.sign_in import (
    Redeem,
    SignInDialog,
    SignInFailed,
    SignInProblem,
    confirm_sign_out,
)
from polyglotic_desktop.ui.widgets import TextDialog
from polyglotic_desktop.ui_next import style
from polyglotic_desktop.ui_next.account_page import AccountPage as NextAccountPage
from polyglotic_desktop.ui_next.caption_window import notice_text
from polyglotic_desktop.ui_next.caption_windows import CaptionWindows
from polyglotic_desktop.ui_next.help_page import HelpPage as NextHelpPage
from polyglotic_desktop.ui_next.home import HomePage
from polyglotic_desktop.ui_next.languages import own_targets, taken_off_note
from polyglotic_desktop.ui_next.learning_page import LearningPage
from polyglotic_desktop.ui_next.main_window import MainWindow as NextMainWindow
from polyglotic_desktop.ui_next.plan import plan_text
from polyglotic_desktop.ui_next.save_folder import SaveFolder
from polyglotic_desktop.ui_next.settings_page import SettingsPage
from polyglotic_desktop.ui_next.transcripts import Transcripts
from polyglotic_desktop.ui_next.views.app_choices import AppChoice, app_choices
from polyglotic_desktop.ui_next.views.arrivals import Arrival
from polyglotic_desktop.ui_next.views.caption_window import (
    LIMIT,
    CaptionLook,
    Notice,
    WindowChoices,
    minutes_used_up,
    slowed_now,
)
from polyglotic_desktop.ui_next.views.home import (
    AppRow,
    AppStatus,
    HomeState,
    ListeningState,
    Picker,
    PickerView,
    addable,
    offer_start_with_windows,
    sample_state,
)
from polyglotic_desktop.ui_next.views.lab import CaptionLab
from polyglotic_desktop.ui_next.views.learning import cards as learning_cards
from polyglotic_desktop.ui_next.views.lookup import WordAt
from polyglotic_desktop.ui_next.views.panels import (
    LanguagesView,
    LookView,
    SessionLanguages,
    Timing,
    TimingView,
)
from polyglotic_desktop.ui_next.views.placement import Rect
from polyglotic_desktop.ui_next.views.plan import PlanLine, PlanShown, plan_line
from polyglotic_desktop.ui_next.word_speech import WordSpeech
from polyglotic_desktop.ui_next.words_page import OpenLanguages, WordsPage

if TYPE_CHECKING:  # imported where first used, after the window's first paint
    from polyglotic_desktop.connection import protocol
    from polyglotic_desktop.connection.client import Connection
    from polyglotic_desktop.connection.exchange import DataExchange
    from polyglotic_desktop.connection.feedback import Outcome
    from polyglotic_desktop.connection.protocol import Os
    from polyglotic_desktop.connection.session import Status
    from polyglotic_desktop.connection.sign_in import RedeemResult
    from polyglotic_desktop.platform.audio_buffer import AudioBuffer
    from polyglotic_desktop.platform.speaking import SpeakerThread
    from polyglotic_desktop.platform.speech_detection import Audio
    from polyglotic_desktop.platform.speech_pipeline import SpeechPipeline

log = logging.getLogger(__name__)

APP_CHECK_MS = 5000  # how often to look for a chosen app that isn't open
HEARING_MS = 100  # how often the listening mark asks whose speech is under way
EXPOSURE_DAYS_MS = 3_600_000  # how often to hand over finished days' exposures
VOICES_AFTER_START_MS = 2000  # Windows' voices looked for after the start (286)

LOG_BYTES, LOG_FILES = 1_000_000, 3  # installed: the log file, rotated
CAPTION_LOG_FILE = "captions.log"
CAPTION_LOG_BYTES, CAPTION_LOG_FILES = 2_000_000, 4
"""The caption log: 10 MB at most - about 100,000 lines, some hours of
busy listening (ids, sizes and times; never caption text)."""

CRASH_NOTE = "crashed.json"  # an error nothing caught, for the next start


def installed() -> bool:
    """Running as the packed app (PyInstaller), not from source."""
    return bool(getattr(sys, "frozen", False))


def third_party_notices() -> str | None:
    """THIRD_PARTY_NOTICES.md, beside the packed app's `Polyglotic.exe`
    (tools/package/build.py puts it there); None from source or if it's
    missing."""
    if not installed():
        return None
    try:
        return (Path(sys.executable).parent / "THIRD_PARTY_NOTICES.md").read_text(
            encoding="utf-8"
        )
    except OSError:
        return None


def dictionaries_folder() -> Path:
    """The dictionary files: beside the packed app's `Polyglotic.exe`, as
    separate, unlocked files (decision 0009); from source, where
    `tools.dictionaries.build` writes them."""
    if installed():
        return Path(sys.executable).parent / "dictionaries"
    return Path("build/dictionaries")


TASKBAR_ID = "Polyglotic.Desktop"
"""The ID Windows' taskbar knows the app by from source (its AppUserModelID:
windows grouped, pinned and drawn under it), not `python.exe`'s. Installed,
the installer's stands (decision 0051). Fixed once testers pin the app: a
changed ID leaves their pins behind."""


SERVER = "https://api.polyglotic.io"
"""The live server, built into every installed copy (the domain since
2026-11-09; the tunnel's address since 2026-11-11, polyglotic-hq DECISIONS
#108). Changed only by a pull request, never by the build (decision
0015); `--server` overrides it for development, and for the PC the server
runs on."""

CREDENTIALS_ELSEWHERE = "Polyglotic/device@{server}"
"""The Credential Manager entry for a server other than `SERVER` (a test
server, from source): one per server, so signing in to one never replaces
another's sign-in (polyglotic-hq 288: on 2026-11-11 the from-source copy's
test-server token sat in the installed copy's entry, which the live server
refused, and the installed copy asked for a code). `SERVER`'s is the
adapter's own, `Polyglotic/device`, as every installed copy has it."""


def credentials_entry(server: str, named: str | None) -> str | None:
    """The device token's entry: `named` (`--credentials`) if given; None -
    the app's own - for `SERVER`; else `CREDENTIALS_ELSEWHERE` for this
    server's host and port."""
    if named:
        return named
    if server.rstrip("/") == SERVER:
        return None
    return CREDENTIALS_ELSEWHERE.format(server=urlsplit(server).netloc or server)


UPDATES = "https://updates.polyglotic.io/"
"""The update feed, built into every installed copy (decision 0015). Not
served yet on 2026-11-11: the first friends' builds find no feed and stay
as installed. `--updates` overrides it to try updates from a folder on
this PC."""
UPDATES_AT_EXIT_SEC = 5.0  # at quit, how long to wait for the updater
RFC8032_TEST_1 = (  # key, signature of the empty message (RFC 8032, 7.1)
    "11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=",
    (
        b"5VZDAMNgrHKQhuLMgG6CioSHfx645dl02HPgZSJJAVVfuIIVkKM7rMYeOXAc+bRr0lv18Fl"
        b"bviRlUUFDjnoQCw=="
    ),
)

FEED_KEYS: tuple[str, ...] = ("T9JEreM5nPkehQOMIfPbjUz1+UoZ73pUJ7rslb72xBs=",)
"""The public keys (Ed25519, base64) the update feed must be signed with
(decision 0019) - on since 0.1.1, with the key the user made on 2026-11-11
(polyglotic-hq DECISIONS.md #97). Every feed and package is checked first,
and an unsigned or tampered one is refused. Empty would turn it off:
Velopack reads the feed as it is (0.1.0 did). Up to two keys while one replaces
the other. Changed only by a pull request, like the addresses."""


def updater(feed: str) -> VelopackUpdater:
    """The installer's updates from `feed`, checked against `FEED_KEYS` when
    it's the built-in feed and they're set. Checked packages are kept beside
    `current` in the install folder (Velopack's place for files that may go
    with an uninstall)."""
    release = this_release()
    signed = feed == UPDATES and bool(FEED_KEYS)
    return VelopackUpdater(
        feed,
        FEED_KEYS if signed else (),
        release.channel,
        release.version,
        Path(sys.executable).parent.parent / "verified-feed",
    )


class NoOsAdapters(RuntimeError):
    """This OS has no adapters yet: what's missing is in the message."""


@dataclass(frozen=True)
class OsAdapters:
    """The OS's own pieces, as `main` wires them - each a port's
    implementation (`ports/capture.py`, `ports/credentials.py`,
    `ports/system.py`), picked by `os_adapters` (decision 0038)."""

    app_list: Callable[[], AppList]
    app_capture_support: Callable[[], AppCaptureSupport]
    """Whether this Windows captures one app alone: yes, try, or no
    (decision 0076)."""
    app_capture_trial: Callable[[], AppCaptureTrial]
    app_capture: Callable[[int, str, AppCaptureTrial | None], AudioCapture]
    everything_else_capture: Callable[[int, AppCaptureTrial | None], AudioCapture]
    windows_build: Callable[[], str]
    """Windows' build and update (`19045.5131`), for the log's line on
    capturing apps one by one (decision 0076)."""
    system_capture: Callable[[], AudioCapture]
    mic_capture: Callable[[], AudioCapture]
    outputs_playing: Callable[[], int | None]
    """How many outputs play sound now (None: Windows can't say), for the
    caption log's line on each mic-bleed check (polyglotic-hq 290)."""
    credentials: Callable[[str | None], CredentialStore]
    """The device token's store: a named one (`credentials_entry`), else the
    app's."""
    hotkeys: Callable[[Mapping[str, Callable[[], None]]], Hotkeys]
    sound_out: Callable[[], SoundOut]
    """Plays the sample aloud (176)."""
    speaker: Callable[[], SpeakerThread]
    """Says a looked-up word aloud in one of the OS's own voices (polyglotic-hq
    286, decision 0077): the `Speaker` port on a thread of its own."""
    start_at_sign_in: Callable[[str], StartWithWindows]
    """The app, at this executable, starting when the learner signs in (176)."""
    keys: KeyState
    on_top: Callable[[], OnTop]
    foreground_watch: Callable[[Callable[[], None]], ForegroundWatch]
    light_taskbar: LightTaskbar
    taskbar_identity: TaskbarIdentity
    """The app's ID on the taskbar (decision 0051)."""
    store_package: StorePackage
    """The Microsoft Store's package this copy runs from, if it does
    (decision 0056)."""
    os_name: Callable[[], Os]
    os_version: OsVersion
    data_folder: DataFolder
    show_error: ErrorBox
    seconds_since_launch: LaunchClock
    hold_key: Callable[
        [str, Callable[[], None], Callable[[], None], Callable[[], None]], HoldKey
    ]
    """Dictation's key, held (polyglotic-hq 283, 289): the key as kept, and
    what to call when it goes down, comes up, and is part of a shortcut."""
    type_text: TypeText
    keyboard_window: KeyboardWindow
    common_apps: tuple[CommonApp, ...] = ()
    """Browsers and the main apps a caption window lists before they play."""


def os_adapters(system: str = sys.platform) -> OsAdapters:
    """The adapters of the OS this runs on (`system`: `sys.platform`'s
    name) - the one place that picks them, imported only now, so the rest
    of the app (and its tests) load on any OS. Raises `NoOsAdapters` naming
    what's missing where there are none yet (polyglotic-hq 171: macOS and
    Linux)."""
    if system != "win32":
        raise NoOsAdapters(
            f"Polyglotic has no adapters for this OS ({system}) yet:"
            " platform/macos or platform/linux would provide ports/capture.py's,"
            " ports/credentials.py's and ports/system.py's (decision 0038)"
        )
    from polyglotic_desktop.adapters import windows_credentials
    from polyglotic_desktop.platform.windows import (
        apps,
        capture,
        categories,
        devices,
        error_box,
        hotkeys,
        keys,
        on_top,
        package,
        process,
        sound,
        startup,
        taskbar,
        text_input,
    )
    from polyglotic_desktop.platform.windows import system as windows

    def speaker() -> SpeakerThread:
        """Windows' voices, imported only now: never on the start's path."""
        from polyglotic_desktop.platform.speaking import SpeakerThread
        from polyglotic_desktop.platform.windows import voices

        return SpeakerThread(voices.WindowsVoices(), voices.WaveOut)

    def credentials(target: str | None) -> CredentialStore:
        store = windows_credentials.WindowsCredentialStore
        return store(target) if target else store()

    return OsAdapters(
        app_list=apps.WindowsAppList,
        app_capture_support=capture.app_capture_support,
        app_capture_trial=capture.Trial,
        app_capture=capture.AppCapture,
        everything_else_capture=capture.EverythingElseCapture,
        windows_build=windows.windows_build,
        system_capture=capture.SystemCapture,
        mic_capture=capture.MicCapture,
        outputs_playing=devices.outputs_playing,
        credentials=credentials,
        hotkeys=hotkeys.GlobalHotkeys,
        sound_out=sound.PlayAloud,
        speaker=speaker,
        start_at_sign_in=startup.RunAtSignIn,
        keys=keys.held,
        on_top=on_top.WindowsOnTop,
        foreground_watch=on_top.ForegroundWatch,
        light_taskbar=taskbar.light_taskbar,
        taskbar_identity=taskbar.app_identity,
        store_package=package.store_package,
        os_name=windows.os_name,
        os_version=windows.os_version,
        data_folder=windows.data_folder,
        show_error=error_box.show_error,
        seconds_since_launch=process.seconds_since_launch,
        hold_key=hotkeys.HoldKey,
        type_text=text_input.type_text,
        keyboard_window=text_input.keyboard_window,
        common_apps=categories.COMMON_APPS,
    )


def listening_settings(
    value: AppSettings,
    own: Mapping[SourceId, tuple[Language, ...]] | None = None,
    spoken: Mapping[SourceId, Language | None] | None = None,
) -> ListeningSettings:
    """What the server needs from the user's settings. `own`: each source's
    languages from the new interface's caption windows (the developer
    switch; none: Original only). The session's targets are then all of
    theirs together - or, if every window is Original only, today's as
    before, which an older server translates into and the windows don't
    show. `spoken`: each source's spoken language from its window (None:
    Detect); the session's is then the one they all name, or Detect
    (`agreed_language`: what a server before 2026-11-09 hears every
    source as) - without windows, today's setting as before. Dictation,
    when it's on, is a source of its own: never translated, heard in its
    own language (decision 0073) - left out of the session's own."""
    targets = tuple(Language(t) for t in value.targets)
    if own:
        together = tuple(dict.fromkeys(t for langs in own.values() for t in langs))
        targets = together or targets
    heard = Language(value.spoken_language) if value.spoken_language else None
    if spoken:
        heard = agreed_language(spoken.values())
    source_targets, source_spoken = dict(own or {}), dict(spoken or {})
    if value.dictation:  # never translated; heard as chosen, or detected (0073)
        source_targets[DICTATION] = ()
        chosen = value.dictation_language
        source_spoken[DICTATION] = Language(chosen) if chosen else None
    return ListeningSettings(
        spoken_language=heard,
        targets=targets,
        source_targets=source_targets,
        source_spoken=source_spoken,
        second_languages={
            Language(t): Language(s) for t, s in value.second_languages.items()
        },
        spelling_hints=value.spelling_hints,
        # Quick preview's lines are always translated (polyglotic-hq 268,
        # DECISIONS.md #101: +65 ms for the learner in 243's phase 2; the
        # server's give-way drops overtaken ones at the peak), and so are
        # Steady's - the longest wait for text's only (277); Live updates'
        # as the learner's "Translate live captions" says
        translate_live=value.caption_mode.provisional_lines
        or (value.translate_live and value.caption_mode is CaptionMode.LIVE),
    )


SETTLE_MS = 300
"""How long a change waits for the next before the session is handed the
listening settings: a control dragged hands over its last value once it
stops, never each mouse move (polyglotic-hq 273)."""


class TakesSettings(Protocol):
    """What the settings are handed to: the listening session."""

    def change_settings(self, settings: ListeningSettings) -> None: ...


class SettingsHandoff(QObject):
    """The listening settings handed to the session once a change has
    settled - `SETTLE_MS` after the last - and only when what the server
    needs differs from what the session last had (polyglotic-hq 273: a
    drag of the panel's slider sent the server a settings message on every
    mouse move; it answered `rate_limited` six times, dropping what came
    with them, and each hand-over held the interface up to 410 ms). A drag
    of a control the server doesn't need - the look - hands over nothing.
    `session`: the listening session now, if any; `chosen`: the listening
    settings now."""

    def __init__(
        self,
        session: Callable[[], TakesSettings | None],
        chosen: Callable[[], ListeningSettings],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session, self._chosen = session, chosen
        self._last: tuple[TakesSettings, ListeningSettings] | None = None
        self._settle = QTimer(self, singleShot=True, interval=SETTLE_MS)
        self._settle.timeout.connect(self.hand_over)

    @property
    def waiting(self) -> bool:
        """A change waits to settle."""
        return self._settle.isActive()

    def changed(self) -> None:
        """Something the listening settings come from changed: handed over
        once nothing else has for `SETTLE_MS`."""
        self._settle.start()

    def started(self, session: TakesSettings, settings: ListeningSettings) -> None:
        """A session started with `settings`: they aren't handed it again."""
        self._last = (session, settings)

    def hand_over(self) -> None:
        """The settings now, to the session - unless it has them already."""
        self._settle.stop()
        session = self._session()
        if session is None:
            return
        now = self._chosen()
        last = self._last
        if last is not None and last[0] is session and last[1] == now:
            return
        self._last = (session, now)
        session.change_settings(now)


def captioned_apps(
    value: AppSettings, per_app: bool, app_id: Callable[[str], SourceId]
) -> list[tuple[str, SourceId]]:
    """The caption windows' sources, in order, each with its key: the
    first LIMIT apps picked (by name), then everything else the PC plays
    beside the one app, if it's on; or everything the PC plays, one window
    ("system") - also for apps picked where Windows can't capture one app
    alone (Windows 10)."""
    if not value.source_chosen:
        return []
    if value.whole_system or not per_app:
        return [(SOURCE_KEY_SYSTEM, WHOLE_SYSTEM)]
    picked = [(name, app_id(name)) for name in value.apps[:LIMIT]]
    if value.captions_everything_else:
        picked.append((SOURCE_KEY_EVERYTHING_ELSE, EVERYTHING_ELSE))
    return picked


def chosen_capture(value: AppSettings) -> Capture:
    """What the learner chose to caption, for `source_selected`: the mode,
    how many apps are picked (at most LIMIT), and their own speech."""
    return capture_of(
        value.source_chosen,
        value.whole_system,
        0 if value.whole_system else len(value.apps[:LIMIT]),
        value.caption_mic,
        value.captions_everything_else,
    )


def captured(value: AppSettings) -> AppSettings:
    """What capture follows with the new interface's caption windows: the
    first LIMIT apps picked only. Home's picker adds no 4th (`adding_app`);
    this keeps one picked in today's interface from being captured with no
    window."""
    return replace(value, apps=value.apps[:LIMIT])


def caption_look(value: AppSettings) -> CaptionLook:
    """How every caption window looks: today's Captions page's settings."""
    return CaptionLook(
        opacity=value.opacity,
        background=value.background_color,
        original=value.original_color,
        translation=value.translation_color,
        font=value.caption_font,
        show_original=value.show_original,
        show_language=value.show_language,
        show_source=value.show_source,
        show_delay=value.show_delay,
        fade_after=value.fade_after,
        arrival=Arrival(value.caption_arrival),
        word_links=WordLinks(value.word_links),
        link_detail=LinkDetail(value.link_detail),
        link_line=LinkLine(value.link_line),
        link_gap=LinkGap(value.link_gap),
        introductions=value.word_introductions,
        preview=value.caption_mode.provisional_lines,
        lab=CaptionLab.from_stored(value.caption_lab),
    )


def second_language_chosen(
    value: AppSettings, target: str, second: str
) -> dict[str, object]:
    """The settings change a window's "Lines already in ..." asks for: lines
    already in `target` shown in `second` - "" (or `target` itself): left as
    they are. Kept by language, so every window with `target` follows
    (263)."""
    seconds = dict(value.second_languages)
    if second and second != target:
        seconds[target] = second
    else:
        seconds.pop(target, None)
    return {"second_languages": seconds}


def stop_captioning(value: AppSettings, key: str) -> dict[str, object]:
    """The settings change a caption window's close (or Home's x) asks for:
    its app unticked - with everything else beside it, which goes with its
    one app; for everything else, that alone; for everything the PC plays,
    nothing captioned."""
    if key == SOURCE_KEY_EVERYTHING_ELSE:
        return {"everything_else": False}
    off = {"everything_else": False} if value.everything_else else {}
    if key == SOURCE_KEY_SYSTEM:
        return {"whole_system": False, "apps": (), **off}
    return {"apps": tuple(app for app in value.apps if app != key), **off}


def switching_app(value: AppSettings, old: str, new: str) -> dict[str, object] | None:
    """The settings change a window's Captioning list asks for (F12, 249):
    app `new` captioned in `old`'s place - in its order, with its colour -
    or None if `new` is captioned already, or `old` isn't."""
    if new == old or new in value.apps or old not in value.apps:
        return None
    colours = dict(value.source_colors)
    colours[new] = colours.get(old) or value.source_colors_for([old])[old]
    return {
        "apps": tuple(new if app == old else app for app in value.apps),
        "source_colors": colours,
    }


WINDOW_NOTICES = {
    ConnectionState.WAITING: Notice.RECONNECTING,
    ConnectionState.SERVER_BUSY: Notice.SERVER_BUSY,
    ConnectionState.SIGN_IN_NEEDED: Notice.NOT_SIGNED_IN,
    ConnectionState.UPDATE_NEEDED: Notice.UPDATE_NEEDED,
    ConnectionState.PLUS_ENDED: Notice.PLUS_ENDED,
    ConnectionState.STOPPED: Notice.STOPPED,
}
"""The session's states a caption window says on its notice line."""

UNREACHABLE_NOTICES = {
    Unreachable.OFFLINE: Notice.OFFLINE,
    Unreachable.NO_ANSWER: Notice.CANT_REACH,
    Unreachable.DOWN: Notice.SERVER_DOWN,
    Unreachable.RESTARTING: Notice.SERVER_RESTARTING,
    Unreachable.SERVER_ERROR: Notice.SERVER_PROBLEM,
    Unreachable.BLOCKED: Notice.BLOCKED,
    Unreachable.NOT_SECURE: Notice.NOT_SECURE,
    Unreachable.CLOCK: Notice.CLOCK,
    Unreachable.TOO_MANY_SESSIONS: Notice.TOO_MANY_SESSIONS,
    Unreachable.TOO_MANY_TRIES: Notice.TOO_MANY_TRIES,
}
"""Waiting to try again: what a caption window says, by why the server
can't be reached (polyglotic-hq 251) - in place of "Reconnecting"."""


def window_notice(
    state: ConnectionState, unreachable: Unreachable | None
) -> Notice | None:
    """What a caption window (or a transcript) says of the session's state."""
    if state is ConnectionState.WAITING and unreachable is not None:
        return UNREACHABLE_NOTICES[unreachable]
    return WINDOW_NOTICES.get(state)


def wire_caption_windows(
    windows: CaptionWindows, desktop: DesktopApp, send_settings: Callable[[], None]
) -> None:
    """The caption windows in step with the app: captions, notices,
    pause, today's free minutes used (the server's count) and the listening
    mark reach them - and signed out, they go until the learner signs in
    (`CaptionWindows`); lock and hide every window are the app's commands
    (tray, Home, hotkeys), which the windows' own buttons check; "Caption
    my own speech" is on while any window shows my speech, and turns it on
    or off in every window; Learning's changes redraw the highlights; a
    window's close unticks its app; its timing chip sets the session's;
    each window's label follows its app's source as it's found;
    All caption settings... opens Settings > Captions (`Hub`) and Open transcript its
    transcript window (`wire_transcripts`); "Looks wrong?" opens the
    comparison, in the languages the line's window shows."""
    windows.languages_changed.connect(send_settings)
    windows.mic_wanted.connect(desktop.caption_mic.setChecked)
    desktop.caption_mic.toggled.connect(
        lambda on: (
            windows.set_show_mic_everywhere(on)
            if on != windows.show_mic_anywhere
            else None
        )
    )
    windows.lock_wanted.connect(lambda: desktop.lock_windows.setChecked(True))
    windows.hide_wanted.connect(lambda: desktop.hide_windows.setChecked(True))
    # what a locked window says unlocks it: the hotkey as it is now - none if
    # another app took it (`hotkeys_taken`) - set before the windows lock
    lock = desktop.lock_windows
    windows.set_unlock_keys(shortcut_text(lock))
    lock.changed.connect(lambda: windows.set_unlock_keys(shortcut_text(lock)))
    desktop.lock_windows.toggled.connect(windows.set_locked)
    desktop.hide_windows.toggled.connect(windows.set_hidden)
    windows.set_locked(desktop.lock_windows.isChecked())
    windows.set_hidden(desktop.hide_windows.isChecked())
    windows.stop_wanted.connect(
        lambda key: desktop.settings.update(
            **stop_captioning(desktop.settings.value, key)
        )
    )
    windows.timing_wanted.connect(
        lambda mode: desktop.settings.update(caption_mode_chosen=mode)
    )
    windows.second_language_wanted.connect(
        lambda target, second: desktop.settings.update(
            **second_language_chosen(desktop.settings.value, target, second)
        )
    )
    windows.looks_wrong.connect(desktop.looks_wrong.check)
    desktop.looks_wrong.languages = lambda caption: windows.targets().get(
        caption.source_id, ()
    )

    def relabel() -> None:
        labels = desktop.source_labels()
        windows.set_labels(labels, labels[MIC].name)

    # an app's source found after its window opened (every start: the windows
    # open before capture starts): the window takes the app's name, not its file's
    desktop.labels_changed.connect(relabel)
    desktop.feed.applied.connect(windows.apply)
    desktop.feed.dictionary_ready.connect(windows.dictionary_ready)
    desktop.feed.checked.connect(windows.use_checked)
    desktop.feed.captioned.connect(windows.captioned)
    desktop.caption_notice.connect(windows.show_notice)
    desktop.connection_changed.connect(
        lambda state, retry_in: windows.set_connection(
            window_notice(state, desktop.unreachable), retry_in
        )
    )
    desktop.pause.toggled.connect(windows.set_paused)
    windows.set_paused(desktop.pause.isChecked())
    desktop.minutes_changed.connect(
        lambda _used, left: windows.set_minutes_used(minutes_used_up(left))
    )
    desktop.captions_failing.connect(windows.set_failing)
    desktop.connection_unstable.connect(windows.set_unstable)
    if desktop.tools is not None:  # highlights drawn again on a Learning change
        desktop.tools.changed.connect(windows.learning_changed)


def wire_transcripts(transcripts: Transcripts, desktop: DesktopApp) -> None:
    """The transcript windows in step with the app: opened from a caption
    window's Open transcript and the tray's Transcript menu; captions, the
    best model's versions, pause and the connection's state reach them;
    their timing sets the session's; "Looks wrong?" opens the comparison;
    Learning's changes recolour saved words."""
    transcripts.windows.transcript_wanted.connect(transcripts.show)
    transcripts.looks_wrong.connect(desktop.looks_wrong.check)
    transcripts.timing_wanted.connect(
        lambda mode: desktop.settings.update(caption_mode_chosen=mode)
    )
    desktop.feed.applied.connect(transcripts.apply)
    desktop.feed.dictionary_ready.connect(transcripts.dictionary_ready)
    desktop.feed.checked.connect(transcripts.use_checked)
    desktop.pause.toggled.connect(transcripts.set_paused)
    transcripts.set_paused(desktop.pause.isChecked())
    # an app's source found after its window opened (every start): the tray's
    # Transcript menu and an open transcript take the name its caption window
    # just took, not its file's (after `wire_caption_windows`' relabel)
    desktop.labels_changed.connect(transcripts.follow)
    desktop.connection_changed.connect(
        lambda state, _retry_in: transcripts.set_connection(
            window_notice(state, desktop.unreachable)
        )
    )
    if desktop.tools is not None:
        desktop.tools.changed.connect(transcripts.learning_changed)
    menu = desktop.tray_menu  # Transcript >, after the caption windows' commands
    actions = menu.actions()
    if desktop.report_problem in actions:
        menu.insertMenu(
            actions[actions.index(desktop.report_problem) - 1], transcripts.menu
        )
    follow_transcripts(transcripts)


def follow_transcripts(transcripts: Transcripts) -> None:
    """The transcripts follow the settings: the window theme, and their
    caption windows' languages, labels and timing."""
    transcripts.set_theme(window_theme())
    transcripts.follow()


def follow_settings(
    windows: CaptionWindows, desktop: DesktopApp, sources: Sources
) -> None:
    """The caption windows follow the settings: the look, the timing,
    second languages, labels, and which apps are captioned."""
    value = desktop.settings.value
    windows.set_look(caption_look(value))
    windows.set_timing(value.caption_mode)
    windows.set_longest_wait(value.max_wait_for_text)
    windows.set_second_languages(
        {Language(t): Language(s) for t, s in value.second_languages.items()}
    )
    captioned = captioned_apps(value, sources.per_app, sources.app_id)
    if sources.sample_shown and not value.source_chosen:  # an app chosen ends it
        captioned.append((SOURCE_KEY_SAMPLE, SAMPLE))
    desktop.set_app_sources(sources.shown())
    labels = desktop.source_labels()
    windows.set_labels(labels, labels[MIC].name)
    windows.set_captioned(captioned)


def session_languages(value: AppSettings, in_use: Sequence[str]) -> SessionLanguages:
    """The Languages panel's value: today's settings, and the caption
    windows' languages (a second-language row each)."""
    return SessionLanguages(
        spoken=value.spoken_language,
        second_languages=dict(value.second_languages),
        translate_live=value.translate_live,
        spelling_hints=value.spelling_hints,
        in_use=tuple(in_use),
        live_updates=value.caption_mode is CaptionMode.LIVE,
    )


def languages_settings(languages: SessionLanguages) -> dict[str, object]:
    """The settings a change in the Languages panel makes."""
    return {
        "spoken_language": languages.spoken,
        "second_languages": dict(languages.second_languages),
        "translate_live": languages.translate_live,
        "spelling_hints": languages.spelling_hints,
    }


def shortcut_text(action: QAction) -> str:
    """`action`'s hotkey as Windows writes it ("Ctrl+Alt+L"); "" for none."""
    return action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)


def look_settings(look: CaptionLook) -> dict[str, object]:
    """The settings a change in the Look panel makes (Quick preview's line
    is the timing's, not the look's)."""
    return {
        "opacity": look.opacity,
        "background_color": look.background,
        "original_color": look.original,
        "translation_color": look.translation,
        "caption_font": look.font,
        "show_original": look.show_original,
        "show_language": look.show_language,
        "show_source": look.show_source,
        "fade_after": look.fade_after,
        "caption_arrival": look.arrival.value,
        "word_links": look.word_links.value,
        "link_detail": look.link_detail.value,
        "link_line": look.link_line.value,
        "link_gap": look.link_gap.value,
        "caption_lab": look.lab.to_stored(),
    }


def window_theme() -> style.Theme:
    """The window theme now - today's theme module's - for the new
    interface's own windows (each dressed by a stylesheet of its own)."""
    return style.Theme(
        asdict(theme.palette(theme.current, theme.current_theme)),
        theme.HEADING_FAMILY,
        dark=theme.current == "dark",
    )


def timing_of(value: AppSettings) -> Timing:
    """The Timing panel's value from the settings: the caption mode, the
    Live updates interval and the longest wait for text (277)."""
    return Timing(
        value.caption_mode, value.live_update_interval, value.max_wait_for_text
    )


class Panels:
    """The shared panels' views, in step with the settings: every panel
    showing them - Settings > Captions and the transcripts' rails - binds
    to these (109's 1.1: one owner, one value). A change in a panel is
    saved with the settings, and the caption windows follow it from
    there - but the look's: the caption windows show it at once, and it's
    saved once it settles (`SETTLE_MS` after the last change), so a drag
    of its slider saves once, not on every mouse move (polyglotic-hq 273:
    each save ran everything that follows the settings, file reads
    included, and held the interface up to 410 ms). The look's reset is
    the look's only: the windows' places are Home's "Reset positions"
    (248's section 2.2)."""

    def __init__(self, settings: Settings, windows: CaptionWindows) -> None:
        self.settings, self.windows = settings, windows
        value = settings.value
        self.languages = LanguagesView(
            session_languages(value, self.in_use()), self._languages_chosen
        )
        self.timing = TimingView(
            timing_of(value),
            lambda t: settings.update(
                caption_mode_chosen=t.mode.value,
                live_update_interval=t.live_interval,
                max_wait_for_text=t.max_wait,
            ),
        )
        self.look = LookView(caption_look(value), self._look_changed)
        self.look_waiting = False
        """A look change waits to be saved."""
        self._look_settles = QTimer(singleShot=True, interval=SETTLE_MS)
        self._look_settles.timeout.connect(self.save_look)
        style.use(window_theme())
        settings.changed.connect(self.follow)
        windows.languages_changed.connect(self.follow)

    def _look_changed(self, look: CaptionLook) -> None:
        """The learner changed the look: the caption windows show it now;
        it's saved once it settles."""
        self.windows.set_look(look)
        self.look_waiting = True
        self._look_settles.start()

    def save_look(self) -> None:
        """The look as the panels have it, saved now if a change waits -
        once it settles, and at quit (`Interface.close`)."""
        self._look_settles.stop()
        if self.look_waiting:
            self.look_waiting = False
            self.settings.update(**look_settings(self.look.value))

    def _languages_chosen(self, languages: SessionLanguages) -> None:
        """A change in the Languages panel (Settings > Captions > Speech),
        saved. Its Spoken language is for every window: each window's own
        is set to it (263) - a window's settings then change its own."""
        if languages.spoken != self.settings.value.spoken_language:
            self.windows.set_spoken_everywhere(languages.spoken)
        self.settings.update(**languages_settings(languages))

    def in_use(self, leaving_out: str | None = None) -> list[str]:
        """The caption windows' languages, in order - but the window of
        `leaving_out` (a source key)'s."""
        found = (
            t
            for source, langs in self.windows.targets().items()
            if source != leaving_out
            for t in langs
        )
        return [str(t) for t in dict.fromkeys(found)]

    def follow(self) -> None:
        value = self.settings.value
        style.use(window_theme())
        self.languages.follow(session_languages(value, self.in_use()))
        self.timing.follow(timing_of(value))
        look = caption_look(value)
        if self.look_waiting:  # the panels' is newer: only the timing's line
            look = replace(self.look.value, preview=look.preview)
        self.look.follow(look)


def _tr_app(text: str) -> str:
    """A source's own name, as today's interface translates it."""
    return QApplication.translate("DesktopApp", text)


def picker_of(
    value: AppSettings,
    found: Sequence[PlayingApp],
    per_app: bool,
    windows: CaptionWindows,
    hidden: bool,
    sample: tuple[bool, bool] = (False, False),
    sample_ended: bool = False,
    fell_back: bool = False,
) -> Picker:
    """Home's app picker: a row per captioned app - the first LIMIT picked,
    and everything else beside one, or everything the PC plays - with its
    label, its colour, whether it's playing, and its window's language and
    my-speech mark; the apps with sound that could be added; and the
    sample (`sample`: whether there's one in the language learned, and
    whether it's on - polyglotic-hq 176; `sample_ended`: it played to its
    end, its window kept - 208). `fell_back`: capturing apps one by one
    was tried here and failed (decision 0076)."""
    colours = value.source_colors_for()
    rows = []
    for key, _ in captioned_apps(value, per_app, lambda name: SourceId(name)):
        if key == SOURCE_KEY_SYSTEM:
            status, own = AppStatus.EVERYTHING, _tr_app("This PC")
        elif key == SOURCE_KEY_EVERYTHING_ELSE:
            status, own = AppStatus.EVERYTHING_ELSE, _tr_app("Everything else")
        else:
            same = [a for a in found if a.name == key]
            own = same[0].title if same else key
            status = (
                AppStatus.PLAYING
                if any(a.playing for a in same)
                else AppStatus.QUIET
                if same
                else AppStatus.NOT_OPEN
            )
        window = windows.windows.get(key)
        choices = (
            window.choices
            if window is not None
            else windows.stored.by_key.get(key, WindowChoices())
        )
        rows.append(
            AppRow(
                key,
                value.source_names.get(key) or own,
                colours.get(key) or value.source_colors_for([key])[key],
                status,
                choices.translate_into,
                choices.show_mic,
            )
        )
    you = AppRow(
        SOURCE_KEY_MIC,
        value.source_names.get(SOURCE_KEY_MIC) or _tr_app("You"),
        colours[SOURCE_KEY_MIC],
        AppStatus.QUIET,
    )
    available = addable(
        [(a.name, a.title, a.playing) for a in found], tuple(value.apps)
    )
    return Picker(
        you=you,
        captioned=tuple(rows),
        available=available,
        whole_system=value.whole_system,
        per_app=per_app,
        fell_back=fell_back and not per_app,
        hidden=hidden,
        everything_else=per_app and value.captions_everything_else,
        sample=sample_state(*sample, value.source_chosen, available, sample_ended),
    )


def adding_app(value: AppSettings, name: str) -> dict[str, object] | None:
    """The settings change Home's + asks for: `name` captioned, with its
    colour fixed now (unticking another later won't change it) - or None
    at the limit (DECISIONS.md #53: 3 apps), or while everything else is
    captioned beside one app (it can be beside one only, #59)."""
    if name in value.apps or len(value.apps) >= LIMIT or value.captions_everything_else:
        return None
    colours = dict(value.source_colors)
    colours.setdefault(name, value.source_colors_for([name])[name])
    changes: dict[str, object] = {
        "apps": (*value.apps, name),
        "whole_system": False,
        "source_colors": colours,
    }
    if value.everything_else:  # kept while it didn't apply: not with this app
        changes["everything_else"] = False
    return changes


def everything_else_change(value: AppSettings, on: bool) -> dict[str, object] | None:
    """The settings change Home's "Also caption everything else" asks for:
    on with one app picked only (None otherwise), with its colour fixed now,
    as an app's is when it's added; or off."""
    if not on:
        return {"everything_else": False}
    if value.whole_system or len(value.apps) != 1:
        return None
    key = SOURCE_KEY_EVERYTHING_ELSE
    colours = dict(value.source_colors)
    on_now = replace(value, everything_else=True)
    colours.setdefault(key, on_now.source_colors_for()[key])
    return {"everything_else": True, "source_colors": colours}


def renaming(value: AppSettings, key: str, text: str, own: str) -> dict[str, object]:
    """The learner's name for a source; empty, or its own: none."""
    names = dict(value.source_names)
    name = text.strip()[:MAX_SOURCE_NAME]
    if name and name != own:
        names[key] = name
    else:
        names.pop(key, None)
    return {"source_names": names}


class Hub:
    """The main window (109's section 7): Home - the state, the app picker,
    the Languages and Timing panels, the caption windows' commands - and
    Words, Account, Settings and Help (109's step 6), wired to the app's
    commands and today's dialogs. It follows the settings, the apps with
    sound, the caption windows and the session's state (`DesktopApp`'s),
    and says the state in the tray's tooltip; the tray, "Looks wrong?" and
    the first run bring it forward (`show`); the picker's commands go to
    the settings and the caption windows."""

    def __init__(
        self,
        desktop: DesktopApp,
        windows: CaptionWindows,
        panels: Panels,
        apps: AppsWithSound,
        per_app: bool,
        save_folder: SaveFolder | None = None,
        opened: OpenLanguages | None = None,
    ) -> None:
        """`save_folder`: where Words' exports open their save dialogs -
        the transcripts' too (`new_interface`). `opened`: which of Words'
        language sections were left open."""
        self.desktop, self.windows, self.apps = desktop, windows, apps
        self.panels, self.per_app = panels, per_app
        self.fell_back = False
        """Capturing apps one by one was tried here and failed (`main`'s
        `AppsOneByOne`, decision 0076): Home says so, with "Try apps again"."""
        self.apps_again: Callable[[], None] | None = None
        """Tries capturing apps one by one again (`main`)."""
        self.busy = False  # the server's pace hint slows live updates
        self.sample: Callable[[bool], None] | None = None
        """Turns the sample on or off (`main`, once listening is wired)."""
        self._samples: dict[str | None, bool] = {}
        """Whether there's a sample, by language learned (`_has_sample`)."""
        self.sample_on = False
        self.sample_ended = False  # played to its end, its window kept (208)
        self.update_found: UpdateNow | None = None
        """What the updater found after the server refused this version."""
        self._shown = False
        self._retry_at: float | None = None
        """When the session tries to reconnect next (`time.monotonic`)."""
        self.picker = PickerView(self._picker(), self)
        self.home = HomePage(
            self.picker,
            desktop.pause,
            desktop.lock_windows,
            desktop.hide_windows,
            theme.SOURCE_COLORS,
        )
        self.home.add_feedback(desktop.report_problem, desktop.suggest)
        self.startup: StartWithWindows | None = None
        """Starting with Windows - the installed app only (`main`)."""
        self._captions = 0  # finished captions shown in this run
        desktop.feed.captioned.connect(self._captioned)
        self.home.start_with_windows_answered.connect(self._start_with_windows)
        self.home.reset_positions_wanted.connect(windows.reset_places)
        self.home.level_wanted.connect(self._level_wanted)
        self.home.level_dismissed.connect(
            lambda: desktop.settings.update(level_line_dismissed=True)
        )
        self.home.join_wanted.connect(
            lambda: windows.separate() if windows.joined_window else windows.join()
        )
        windows.joined_changed.connect(lambda _: self.follow())
        self.window = NextMainWindow(desktop.quit)
        tr = QApplication.translate
        self.window.add_page("home", tr("MainWindow", "Home"), self.home)
        self.words: WordsPage | None = None
        tools = desktop.tools
        if tools is not None:
            self.words = WordsPage(tools, windows.card, save_folder, opened)
            tools.changed.connect(self.words.learning_changed)
            tools.read_ahead_done.connect(self.words.learning_changed)  # opened early
            self.words.change_level_wanted.connect(self.change_level)
            self.window.add_page("words", tr("MainWindow", "Words"), self.words)
        self.account = NextAccountPage()
        self.home.sign_in_wanted.connect(self.account.sign_in.trigger)
        self.home.get_plus_wanted.connect(self.account.get_plus.click)
        self.account.add_feedback(desktop.report_problem, desktop.suggest)
        # Learning, between Words and Account (polyglotic-hq 262, 248's Q2 A)
        self.level_of: Callable[[str], LevelCurve | None] | None = None
        """Another full dictionary's level, as it was kept (`main`)."""
        self.learning = LearningPage(self.account.delete_learning)
        self.learning.change_level_wanted.connect(self.change_level)
        self.learning.languages_wanted.connect(
            lambda languages: desktop.settings.update(**learning_changes(languages))
        )
        self.learning.introductions_chosen.connect(
            lambda choice: desktop.settings.update(**introductions_changes(choice))
        )
        self.learning.words_wanted.connect(lambda: self.window.go_to("words"))
        self.window.add_page("learning", tr("MainWindow", "Learning"), self.learning)
        self.window.add_page("account", tr("MainWindow", "Account"), self.account)
        self.settings = SettingsPage(
            [(key, look.name) for key, look in theme.THEMES.items()],
            desktop.hotkeys,
            desktop.work_with_us,
            interface_language.picker(),
            look=panels.look,
            timing=panels.timing,
            speech=panels.languages,
        )
        app = QApplication.instance()
        running = interface_language.in_use(app) if app else interface_language.ENGLISH
        self.settings.show_draft(interface_language.is_draft(running))
        self.settings.translation_feedback_wanted.connect(
            lambda: desktop.feedback_wanted.emit("suggestion")
        )
        self.settings.learning_wanted.connect(lambda: self.window.go_to("learning"))
        windows.all_settings_wanted.connect(self.open_caption_settings)
        self.settings.interface_language_chosen.connect(
            lambda code: desktop.settings.update(interface_language=code or None)
        )
        self.settings.theme_chosen.connect(
            lambda key: desktop.settings.update(theme=key)
        )
        self.settings.window_theme_chosen.connect(
            lambda mode: desktop.settings.update(window_theme=mode)
        )
        self.settings.text_size_chosen.connect(
            lambda size: desktop.settings.update(app_text_size=size)
        )
        self._show_theme()
        desktop.settings.changed.connect(self._show_theme)
        # the app's text size: `main` applied it at start; a change, at once
        self._text_size = desktop.settings.value.app_text_size
        desktop.settings.changed.connect(self._follow_text_size)
        self.window.add_page(
            "settings", tr("MainWindow", "Settings"), self.settings, "foot"
        )
        self.help = NextHelpPage(
            desktop.caption_facts,
            lambda: tools.dictionary_problem if tools is not None else None,
            tools.is_chinese if tools is not None else True,
            lambda: tools.learning_set_aside if tools is not None else None,
            lambda: tools.learning_unsaved if tools is not None else False,
        )
        self.help.report_wanted.connect(desktop.check_report_wanted)
        self.window.add_page("help", tr("MainWindow", "Help"), self.help, "foot")
        self.window.go_to("home")
        self.retheme()
        desktop.looks_wrong.window = self.window  # its card opens over this window
        desktop.window_wanted.connect(self.show)
        self.window.hidden_to_tray.connect(desktop.note_in_tray)  # once: still running
        desktop.themed.connect(self.retheme)
        self.window.text_size_changed.connect(self.retheme)  # the logo at it
        desktop.minutes_changed.connect(self.home.state.set_minutes)
        desktop.home_notice.connect(self.home.state.set_notice)
        desktop.banner_in_view = self.banner_in_view  # else the tray says it too
        desktop.captions_failing.connect(self.home.state.set_failing)
        desktop.connection_unstable.connect(self.home.state.set_unstable)
        if tools is not None:  # out at the start, or when a query fails (199)
            tools.dictionary_out.connect(
                self._dictionary_out, Qt.ConnectionType.QueuedConnection
            )
            self._dictionary_out()
            # its learning data set aside at the start, or found damaged
            # later (polyglotic-hq 206)
            self.home.state.set_learning_set_aside(tools.learning_set_aside)
            tools.learning_damaged.connect(
                self._learning_data_changed, Qt.ConnectionType.QueuedConnection
            )
            # deleted on this PC, with the files set aside (213)
            tools.learning_deleted.connect(
                self._learning_data_changed, Qt.ConnectionType.QueuedConnection
            )
        self._learning_shown: tuple[object, ...] | None = None
        """The settings Learning's page shows, as it last showed them."""
        self.show_learning()
        desktop.settings.changed.connect(self._learning_settings_changed)
        if tools is not None:  # a level picked or changed
            tools.changed.connect(self._learning_changed)
        desktop.connection_changed.connect(self._connection_changed)
        desktop.pause.toggled.connect(self.follow)
        desktop.hide_windows.toggled.connect(self.follow)
        desktop.settings.changed.connect(self.follow)
        windows.languages_changed.connect(self.follow)
        windows.mic_wanted.connect(self.follow)
        apps.found.connect(self.follow)
        self.follow()

    def _dictionary_out(self) -> None:
        """The learner's dictionary is out (polyglotic-hq 199): Home's
        banner says so, and Help's check (it asks when it runs)."""
        tools = self.desktop.tools
        if tools is not None:
            self.home.state.set_dictionary_out(
                tools.dictionary_problem, tools.is_chinese
            )

    def _learning_data_changed(self) -> None:
        """The learning data was found damaged since the start: Home's
        banner says nothing more is saved until a restart (polyglotic-hq
        206). Or the learner deleted it on this PC: the banner no longer
        names a file set aside that went with it (213). Help's check asks
        when it runs."""
        tools = self.desktop.tools
        if tools is not None:
            self.home.state.set_learning_set_aside(
                tools.learning_set_aside, unsaved=tools.learning_unsaved
            )

    def _follow_text_size(self) -> None:
        """The app's text size changed (Settings > App): every window at it
        now - the main window restyles and says so (`text_size_changed`:
        `interface` restyles the others). Only a change: what the settings
        had at start, `main` applied before the first window."""
        size = self.desktop.settings.value.app_text_size
        if size != self._text_size:
            self._text_size = size
            self.window.set_app_text_size(size)

    def _show_theme(self) -> None:
        value = self.desktop.settings.value
        self.settings.show_theme(value.theme, value.window_theme)
        self.settings.show_text_size(value.app_text_size)
        self.settings.show_interface_language(value.interface_language or "")

    def show_plan(self, line: PlanLine) -> None:
        """The account's plan, on Home and Account (polyglotic-hq 185)."""
        self.home.state.set_plan(plan_text(line))
        self.account.show_plan(line)

    def show_learning(self) -> None:
        """Learning's page: the languages being learned, each with what its
        dictionary gives and its level, and the word introductions chosen."""
        value = self.desktop.settings.value
        tools = self.desktop.tools
        running = tools.language if tools is not None else None

        def level_of(code: str) -> LevelCurve | None:
            if tools is not None and code == running:
                return tools.vocabulary.curve
            return self.level_of(code) if self.level_of is not None else None

        languages = value.learning_languages
        self._learning_shown = _learning_settings(value)
        packs = tuple(tools.basic) if tools is not None else ()
        self.learning.show_learning(
            languages,
            learning_cards(languages, running, level_of, packs),
            value.word_introductions,
            running,
            chinese=tools.is_chinese if tools is not None else True,
        )
        if self.words is not None and running is not None:  # whose words (299)
            self.words.show_in_use(running, value.learning)
        self._show_level_line()  # the languages learned decide it too

    def _learning_settings_changed(self) -> None:
        """A setting changed: Learning's page again only if what it shows
        from the settings did - each showing reads another language's
        level from its file (polyglotic-hq 273: on every move of a drag)."""
        if _learning_settings(self.desktop.settings.value) != self._learning_shown:
            self.show_learning()

    def _learning_changed(self, what: str) -> None:
        if what == Changed.LEVEL.value:
            self.show_learning()

    def _show_level_line(self) -> None:
        """Home's line asking for the level, until the learner sets one or
        says Not now - the first run doesn't ask (polyglotic-hq 293). Only
        while there's a level to set: the language learned is the one in
        use, or none is chosen yet - not for a learner of languages with no
        levels (a basic dictionary, or none yet)."""
        tools = self.desktop.tools
        value = self.desktop.settings.value
        self.home.show_level_line(
            tools is not None
            and tools.vocabulary.curve is None
            and not value.level_line_dismissed
            and (
                value.learning == tools.language
                or (value.learning is None and not value.also_learning)
            )
        )

    def _level_wanted(self) -> None:
        """The level line's Set your level: the level picker for the
        language learned, in use now; else Learning, where a language is
        chosen first - its card then has Change your level."""
        tools = self.desktop.tools
        if tools is not None and self.desktop.settings.value.learning == tools.language:
            self.change_level()
        else:
            self.window.go_to("learning")

    def change_level(self) -> None:
        """Words' and Learning's Change your level: today's level picker,
        over the new main window."""
        tools = self.desktop.tools
        if tools is None:
            return
        curve = tools.vocabulary.curve
        current = Level(curve.scheme, curve.picked_level) if curve else None
        picker = LevelPicker(tools.is_chinese, current, self.window)
        if picker.exec():
            tools.vocabulary.set_level(picker.level())

    def open_caption_settings(self) -> None:
        """A caption window's "All caption settings...": the main window in
        front, on Settings > Captions."""
        self.window.go_to("settings")
        self.settings.show_section("captions")
        self.show(picker=False)

    def open_app_settings(self) -> None:
        """The tray's "More languages…" for dictation: the main window in
        front, on Settings > App (polyglotic-hq 283)."""
        self.window.go_to("settings")
        self.settings.show_section("app")
        self.show(picker=False)

    def show(self, picker: bool = True) -> None:
        """The main window in front - on Home, where the learner picks
        what to caption, while nothing is chosen (with `picker`)."""
        if picker and not self.desktop.settings.value.source_chosen:
            self.window.go_to("home")
        if not self._shown:  # its first time: sized to the screen it opens on
            self._shown = True
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                self.window.fit_to(screen.availableGeometry())
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def banner_in_view(self) -> bool:
        """Whether Home's banner is in front of the learner: the main window
        shown on Home, and it - or a dialog over it, such as the report
        just sent from - is the window in front (polyglotic-hq 279)."""
        window = self.window
        if not window.isVisible() or window.isMinimized() or window.current != "home":
            return False
        active = QApplication.activeWindow()
        while active is not None and active is not window:
            active = active.parentWidget()
        return active is window

    def _captioned(self, _source_id: str) -> None:
        """A finished caption shown: after a good session, "Start with
        Windows?" on Home - once ever (polyglotic-hq 176)."""
        self._captions += 1
        startup = self.startup
        value = self.desktop.settings.value
        if offer_start_with_windows(
            self._captions,
            value.start_with_windows_asked,
            startup is not None and startup.enabled(),
            startup is not None,
        ):
            self.desktop.settings.update(start_with_windows_asked=True)
            self.home.offer_start_with_windows()

    def _start_with_windows(self, yes: bool) -> None:
        if yes and self.startup is not None:
            self.startup.set_enabled(True)

    def close(self) -> None:
        """The window closes for good (the app is quitting)."""
        self.window.keep_in_tray = False
        self.window.close()

    def retheme(self) -> None:
        ratio = self.window.devicePixelRatioF()
        logo = icons.logo(round(style.px(28) * ratio), theme.current == "dark")
        logo.setDevicePixelRatio(ratio)
        self.window.set_theme(window_theme(), logo)

    def set_busy(self, busy: bool) -> None:
        """The server's pace hint: "Busy time" on Home's banner when it
        begins slowing the live updates the learner's timing shows - as the
        caption windows say it."""
        mode = self.desktop.settings.value.caption_mode
        if slowed_now(self.busy, busy, mode):
            self.home.state.set_notice(notice_text(Notice.BUSY, None))
        self.busy = busy

    def set_update_found(self, found: UpdateNow) -> None:
        """What the updater found after "update required": Home says what
        to do while the server refuses this version."""
        self.update_found = found
        self.follow()

    def _picker(self) -> Picker:
        return picker_of(
            self.desktop.settings.value,
            self.apps.playing_apps(),
            self.per_app,
            self.windows,
            self.desktop.hide_windows.isChecked(),
            (
                self.sample is not None
                and self._has_sample(
                    sample_language(self.desktop.settings.value, self.desktop.tools)
                ),
                self.sample_on,
            ),
            self.sample_ended,
            self.fell_back,
        )

    def _has_sample(self, learning: str | None) -> bool:
        """Whether there's a sample in `learning`: looked for once per
        language, not on every setting changed (polyglotic-hq 273) - the
        samples come with the app."""
        found = self._samples.get(learning)
        if found is None:
            found = self._samples[learning] = sample_file(learning) is not None
        return found

    def _connection_changed(self, _state: object, retry_in: float | None) -> None:
        """The session's state changed: Home's countdown runs to the next
        try from now, not from whenever Home is next drawn."""
        now = time.monotonic()
        self._retry_at = now + retry_in if retry_in is not None else None
        if self.desktop.connection is ConnectionState.SIGN_IN_NEEDED:
            self.home.state.set_plan(None)  # the plan was the account's
        self.follow()

    def follow(self) -> None:
        value = self.desktop.settings.value
        state = self.desktop.connection
        self.picker.follow(self._picker())
        self.home.show_joined(
            self.windows.joined_window is not None, len(self.windows.windows)
        )
        # the sample's window, kept for lookups once it has ended, captions
        # nothing: no language in use, nor a window (208's finding; 213)
        kept = SOURCE_KEY_SAMPLE if self.sample_ended and not self.sample_on else None
        self.home.show_state(
            HomeState(
                connection=ListeningState(state.value),
                retry_at=self._retry_at,
                paused=self.desktop.pause.isChecked(),
                # the sample playing is captioning: Home follows its session
                chosen=value.source_chosen or self.sample_on,
                languages=tuple(self.panels.in_use(leaving_out=kept)),
                windows=sum(key != kept for key in self.windows.windows),
                speech_shown=self.windows.show_mic_anywhere,
                update_found=self.update_found,
                unreachable=self.desktop.unreachable,
            )
        )
        self.desktop.show_state_title(self.home.state.title_label.text())

    # -- the picker's commands ----------------------------------------------------------

    def add(self, name: str) -> None:
        changes = adding_app(self.desktop.settings.value, name)
        if changes is not None:
            self.desktop.settings.update(**changes)

    def remove(self, key: str) -> None:
        value = self.desktop.settings.value
        self.desktop.settings.update(**stop_captioning(value, key))

    def rename(self, key: str, text: str) -> None:
        own = next(
            (a.title for a in self.apps.playing_apps() if a.name == key),
            {
                SOURCE_KEY_SYSTEM: _tr_app("This PC"),
                SOURCE_KEY_EVERYTHING_ELSE: _tr_app("Everything else"),
                SOURCE_KEY_MIC: _tr_app("You"),
            }.get(key, key),
        )
        value = self.desktop.settings.value
        self.desktop.settings.update(**renaming(value, key, text, own))

    def recolour(self, key: str, colour: str) -> None:
        colours = dict(self.desktop.settings.value.source_colors)
        colours[key] = colour
        self.desktop.settings.update(source_colors=colours)

    def show_window(self, key: str) -> None:
        self.windows.show_window(key)

    def open_transcript(self, key: str) -> None:
        self.windows.transcript_wanted.emit(key)

    def set_whole_system(self, on: bool) -> None:
        self.desktop.settings.update(whole_system=on)

    def set_everything_else(self, on: bool) -> None:
        changes = everything_else_change(self.desktop.settings.value, on)
        if changes is not None:
            self.desktop.settings.update(**changes)

    def set_show_mic(self, key: str, on: bool) -> None:
        self.windows.set_show_mic(key, on)
        self.follow()

    def set_translate_into(self, key: str, code: str) -> None:
        self.windows.set_language(key, code)
        self.follow()

    def refresh(self) -> None:
        self.apps.look()

    def try_sample(self, on: bool) -> None:
        if self.sample is not None:
            self.sample(on)

    def try_apps_again(self) -> None:
        if self.apps_again is not None:
            self.apps_again()


@dataclass
class Interface:
    """The new interface's parts as `main` builds them: the caption windows,
    the transcripts, the shared panels and the main window."""

    windows: CaptionWindows
    transcripts: Transcripts
    panels: Panels
    hub: Hub

    def close(self) -> None:
        """Every window closed, their choices saved (the app is quitting) -
        and a look change still settling."""
        self.panels.save_look()
        self.transcripts.close()
        self.windows.close()
        self.hub.close()


class LearningOffer:
    """The lookup card's "Learn it too?" (`views.lookup.LanguagesOffer`): the
    languages being learned, as the settings keep them for Learning's page
    (DECISIONS.md #65, polyglotic-hq 262)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def asks_about(self, caption_language: str | None) -> str | None:
        return self.settings.value.learning_languages.asks_about(caption_language)

    def learn_too(self, code: str) -> None:
        languages = self.settings.value.learning_languages
        self.settings.update(**learning_changes(languages.added(code)))

    def not_now(self, code: str) -> None:
        languages = self.settings.value.learning_languages
        self.settings.update(**learning_changes(languages.declined(code)))


def new_interface(
    desktop: DesktopApp,
    store: SettingsStore,
    tools: LearningTools | None,
    per_app: bool,
    keys: KeyState | None = None,
    on_top: OnTop | None = None,
    common_apps: Sequence[CommonApp] = (),
) -> Interface:
    """The interface on the app (decisions 0031 and 0032): a caption window
    per app captioned, a transcript per app, the panels they share and the
    main window - for `main` and for `check_install` alike. `keys`: Windows'
    key state (`platform.windows.keys.held`), for the settings popovers;
    `on_top`: Windows' always-on-top band (`platform.windows.on_top`), to
    keep the caption windows above a game that is itself always on top;
    `common_apps`: browsers and the main apps a window's Captioning list
    shows before they play (F12, 249)."""
    windows = CaptionWindows(
        store, MIC, parent=desktop, keys=keys, learner=tools, on_top=on_top
    )
    found_apps = desktop.apps
    assert found_apps is not None  # the app is always given an app list

    def choices_for(key: str) -> list[AppChoice]:
        value = desktop.settings.value
        # the hub's: everything the PC plays from when trying apps fails (0076)
        if not hub.per_app or value.whole_system or key not in value.apps:
            return []  # everything the PC plays, the mic, the sample: no apps
        found = [(a.name, a.title, a.playing) for a in found_apps.playing_apps()]
        common = [(a.name, a.title) for a in common_apps]
        return app_choices(found, common, key, value.apps)

    def switch(key: str, name: str) -> None:
        changes = switching_app(desktop.settings.value, key, name)
        if changes is not None:
            windows.carry(key, name)  # the new app opens where the old one was
            desktop.settings.update(**changes)

    windows.app_choices = choices_for
    windows.app_wanted.connect(switch)
    if windows.card is not None:  # "Learn Japanese too?" (polyglotic-hq 262)
        windows.card.model.offer = LearningOffer(desktop.settings)
    # every save dialog opens where the last save went, or in Documents -
    # never the install folder an update replaces (polyglotic-hq 244)
    save_folder = SaveFolder(store)
    transcripts = Transcripts(
        windows, store, learner=tools, parent=desktop, save_folder=save_folder
    )
    panels = Panels(desktop.settings, windows)
    windows.links_wanted.connect(panels.look.set_links_shown)  # a window's button
    transcripts.panels = panels  # their rails show the same panels
    hub = Hub(
        desktop,
        windows,
        panels,
        found_apps,
        per_app,
        save_folder,
        OpenLanguages(store),
    )
    # the text size changed - Windows' or the app's own (Settings > App)
    hub.window.text_size_changed.connect(transcripts.restyle)
    hub.window.text_size_changed.connect(windows.restyle)  # their chrome
    hub.window.text_size_changed.connect(hub.retheme)  # the logo, at its size
    menu = desktop.tray_menu  # and Qt's other own parts (`style.size_qt_parts`)
    hub.window.text_size_changed.connect(lambda: style.size_qt_parts(menu))
    menu.aboutToShow.connect(lambda: style.size_qt_parts(menu))  # later submenus
    style.size_qt_parts(menu)
    return Interface(windows, transcripts, panels, hub)


def connection_state(
    status: Status, shown: ConnectionState | None = None
) -> tuple[ConnectionState, float | None]:
    """The session's state as Home shows it - and the caption windows and
    transcripts. `shown`: the state shown now. While reconnecting, each try
    is still "Reconnecting" (no countdown while it tries), not "Connecting":
    the windows' notice would go blank for each try (polyglotic-hq 133).
    Likewise "Update needed" stays while the session asks the server again
    whether it takes this version (polyglotic-hq 137), and "Plus has ended"
    while it asks whether the account has Plus again (polyglotic-hq 203)."""
    from polyglotic_desktop.connection.reconnect import StopReason
    from polyglotic_desktop.connection.session import SessionState

    if status.state is SessionState.CONNECTING and shown in (
        ConnectionState.WAITING,
        ConnectionState.SERVER_BUSY,
        ConnectionState.UPDATE_NEEDED,
        ConnectionState.PLUS_ENDED,
    ):
        return shown, None
    if status.state is SessionState.STOPPED:
        return {
            StopReason.SIGN_IN_NEEDED: ConnectionState.SIGN_IN_NEEDED,
            StopReason.UPDATE_REQUIRED: ConnectionState.UPDATE_NEEDED,
            StopReason.LISTENING_MOVED: ConnectionState.MOVED,
            StopReason.LIMIT_REACHED: ConnectionState.PLUS_ENDED,  # 4009 (185)
        }.get(status.stopped or StopReason.CLOSED, ConnectionState.STOPPED), None
    if status.state is SessionState.WAITING and status.server_busy:
        return ConnectionState.SERVER_BUSY, status.retry_in  # not the learner's (208)
    return {
        SessionState.CONNECTING: ConnectionState.CONNECTING,
        SessionState.LISTENING: ConnectionState.LISTENING,
        SessionState.WAITING: ConnectionState.WAITING,
    }[status.state], status.retry_in


def unreachable_shown(
    status: Status,
    shown: ConnectionState | None = None,
    said: Unreachable | None = None,
) -> Unreachable | None:
    """Why the server can't be reached, as Home and the caption windows say
    it: the session's while it waits to try again - and through each try,
    as "Reconnecting" stays (`connection_state`), so the reason doesn't
    blank for each try. `said`: the reason said now (polyglotic-hq 251)."""
    from polyglotic_desktop.connection.session import SessionState

    if status.state is SessionState.WAITING and not status.server_busy:
        return status.unreachable
    if status.state is SessionState.CONNECTING and shown is ConnectionState.WAITING:
        return said
    return None


class BackgroundUpdates:
    """Core's update rules on a thread of their own, one call at a time, so
    the network never holds up start-up or the interface (decision 0017).
    A failure - no network, no feed yet - is logged, never raised. What
    each look found goes to `tell`'s listener, on this thread - the last
    one at once to a listener that comes later: the first look runs before
    the interface is built (polyglotic-hq 299)."""

    def __init__(self, updates: Updates) -> None:
        self.updates = updates
        self._worker = ThreadPoolExecutor(1, thread_name_prefix="updates")
        self._lock = threading.Lock()
        self._listener: Callable[[Found, Update | None], None] | None = None
        self._last: tuple[Found, Update | None] | None = None

    def check(self) -> None:
        self._worker.submit(self._run, "check", self._look)

    def tell(self, listener: Callable[[Found, Update | None], None]) -> None:
        """`listener(found, downloaded)` after each look, from this thread."""
        with self._lock:
            self._listener, last = listener, self._last
        if last is not None:
            listener(*last)

    def _look(self) -> None:
        found = self.updates.look()
        if found not in (Found.UP_TO_DATE, Found.READY):
            log.info("updates: %s", found.value)
        with self._lock:
            self._last = (found, self.updates.downloaded)
            listener, last = self._listener, self._last
        if listener is not None:
            listener(*last)

    def follow(self, channel: str | None) -> None:
        def follow_then_check() -> None:
            if self.updates.follow(channel):
                log.info("following the server's update channel")
                self._look()

        self._worker.submit(self._run, "follow", follow_then_check)

    def restart_when_quitting(self) -> None:
        """The learner's Restart now: what's downloaded applies as the app
        quits, then the new version starts - before `at_exit`, on this
        thread (polyglotic-hq 299)."""
        self._worker.submit(
            self._run, "restart now", self.updates.restart_when_quitting
        )

    def update_now(self, found: Callable[[UpdateNow], None]) -> None:
        """Straight to the updater; `found` is told what it found, on the
        updates' thread - after a failure, whether a downloaded update
        installs at the next start."""

        def update_now_then_say() -> None:
            try:
                outcome = self.updates.update_now()
            except Exception:
                downloaded = self.updates.downloaded is not None
                found(UpdateNow.DOWNLOADED if downloaded else UpdateNow.NONE_YET)
                raise
            found(outcome)

        self._worker.submit(self._run, "update now", update_now_then_say)

    def at_exit(self) -> None:
        """At quit: what must apply as the app exits, then stop."""
        done = self._worker.submit(self._run, "at exit", self.updates.at_exit)
        try:
            done.result(timeout=UPDATES_AT_EXIT_SEC)
        except TimeoutError:
            log.warning("updates: still busy at quit")
        self._worker.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _run(name: str, call: Callable[[], object]) -> None:
        try:
            call()
        except Exception as e:  # noqa: BLE001 - the app runs on without updates
            log.warning("updates: %s failed (%s)", name, type(e).__name__)


class UpdateShown(QObject):
    """What the updates found, on the interface thread (polyglotic-hq
    299): a downloaded update offered on Home - "Version X is ready", what's
    new in two lines, Restart now and Later - and in the tray's menu;
    Settings says what the last look found. Never a window of its own over
    a game or a call, and nothing restarts by itself: Restart now quits as
    Quit does, then the installer applies it and starts the new version."""

    _found = Signal(object, object)

    def __init__(
        self,
        home: HomePage,
        desktop: DesktopApp,
        settings: SettingsPage | None,
        restart: Callable[[], None],
    ) -> None:
        """`settings`: Settings' Updates card (None for the Microsoft
        Store's copy, which the Store updates). `restart`: Restart now."""
        super().__init__(desktop)
        self.offer = RestartOffer()
        self.home, self.desktop, self.settings = home, desktop, settings
        self._found.connect(self._show, Qt.ConnectionType.QueuedConnection)
        home.restart_wanted.connect(restart)
        home.update_later.connect(self._later)
        desktop.install_update.triggered.connect(restart)
        if settings is not None:
            settings.restart_wanted.connect(restart)

    def found(self, found: Found, downloaded: Update | None) -> None:
        """A look's outcome, from the updates' thread."""
        self._found.emit(found, downloaded)

    @Slot(object, object)
    def _show(self, found: Found, downloaded: Update | None) -> None:
        if self.offer.found(downloaded):
            asking = self.offer.asking
            if asking is not None:
                log.info("update %s offered on Home", asking.version)
            self.home.show_update(
                asking.version if asking else None,
                whats_new(asking.notes) if asking else (),
            )
        version = downloaded.version if downloaded else None
        self.desktop.show_update_ready(version)
        if self.settings is not None:  # ready, whatever this look found
            self.settings.show_update(
                Found.READY.value if version else found.value, version
            )

    def _later(self) -> None:
        log.info("update: Later - asked again at the next start")
        self.offer.later()
        self.home.show_update(None)


def plan_shown(plan: protocol.PlanState) -> PlanShown:
    """The server's plan as the plan line reads it. A date that can't be
    read is left out: the line then names no date rather than a wrong one."""
    from polyglotic_desktop.connection.protocol import parse_at

    until = None
    if plan.until is not None:
        with contextlib.suppress(ValueError):
            until = parse_at(plan.until)
    code = plan.message.code if plan.message is not None else None
    return PlanShown(plan.tier, plan.source, plan.status, until, code)


class DictationKeyHeld:
    """Dictation's key, taken from the OS as the settings say
    (polyglotic-hq 283, 289): let go while Settings' key box listens for a
    new one; a key pressed there tried before it's kept - one another
    program has leaves the key before."""

    def __init__(self, hold_key: Callable[[str], HoldKey]) -> None:
        """`hold_key`: the OS's key, as kept ("right_ctrl"), not started."""
        self._hold_key = hold_key
        self._key: HoldKey | None = None
        self.held_as: str | None = None
        """The key held now, as kept; None: none."""
        self.taken = False
        """Another program had the key when it was last taken."""
        self.box_listening = False

    def follow(self, on: bool, key: str) -> bool:
        """Dictation on or off, and its key: taken, or let go. True if
        that changed anything."""
        wanted = key if on and not self.box_listening else None
        if wanted == self.held_as:
            return False
        self.stop()
        self.taken = False
        if wanted is not None:
            self._key = self._hold_key(wanted)
            self.taken = not self._key.start()
            self.held_as = wanted
        return True

    def try_key(self, wanted: str, on: bool) -> bool:
        """A key pressed in Settings: False if another program has it
        (`follow` then takes the one before again); else True - and held
        now, if dictation is `on`."""
        self.stop()  # the key before may share keys with it
        trial = self._hold_key(wanted)
        if not trial.start():
            trial.stop()
            return False
        if on and not self.box_listening:
            self._key, self.held_as = trial, wanted
        else:
            trial.stop()
        return True

    def stop(self) -> None:
        if self._key is not None:
            self._key.stop()
        self._key, self.held_as = None, None


class QtListener(QObject):
    """The session's listener: its calls come on the session's thread and
    go to the interface on the Qt thread. The channel the server names, and
    its "update required", go to the updates."""

    _status = Signal(object)
    _minutes = Signal(float, object)
    _notice = Signal(str)
    _failed = Signal()
    _stalled = Signal(bool)
    _pace = Signal(object)
    _plan = Signal(object)
    plan_shown = Signal(object)
    """The account's plan as its line (`PlanLine`), on the interface thread."""
    busy_changed = Signal(bool)
    """The server's pace hint began (True) or stopped slowing live updates
    - a busy time - on the interface thread."""
    spoken_per_source = Signal(bool)
    """A listening session opened: whether its server uses each caption
    window's spoken language (`welcome.source_fields`; 263), on the
    interface thread."""
    update_found = Signal(object)
    """What the updater found after "update required" (`UpdateNow`), on the
    interface thread: what Home tells the learner to do."""
    cohort_seen = Signal(str)
    """A session opened: the account's test group (`welcome.cohort`), on the
    interface thread (polyglotic-hq 275)."""

    def __init__(
        self,
        desktop: DesktopApp,
        pipeline: SpeechPipeline | None,
        updates: BackgroundUpdates | None = None,
        account: NextAccountPage | None = None,
    ) -> None:
        """`account`: the Account page the session's sign-in state goes to."""
        super().__init__(desktop)
        self.desktop = desktop
        self.pipeline = pipeline
        self.updates = updates
        self.account = account
        self.session_id: str | None = None
        """The last listening session's id, for feedback to name."""
        self.dictated: Callable[[CaptionUpdate], None] | None = None
        """Where dictation's answers go, from the session's thread - never
        the caption feed (`ui.dictation.Dictating.answered`; 0073)."""
        self._status.connect(self._show_status, Qt.ConnectionType.QueuedConnection)
        self._minutes.connect(desktop.set_minutes, Qt.ConnectionType.QueuedConnection)
        self._notice.connect(desktop.show_notice, Qt.ConnectionType.QueuedConnection)
        self._failed.connect(desktop.caption_failed, Qt.ConnectionType.QueuedConnection)
        self._stalled.connect(
            desktop.connection_stalled, Qt.ConnectionType.QueuedConnection
        )
        self._busy = False
        self._pace.connect(self._show_pace, Qt.ConnectionType.QueuedConnection)
        self._plan.connect(self._show_plan, Qt.ConnectionType.QueuedConnection)
        self._held: str | None = None
        """The tier the open listening session holds until it ends (its
        `welcome`'s), on the interface thread; None when none is open."""
        self._last_plan: PlanShown | None = None

    def status_changed(self, status: Status) -> None:
        log.info("session %s", status.state.value)
        if status.session_id is not None:
            self.session_id = status.session_id
        if status.channel is not None and self.updates is not None:
            self.updates.follow(status.channel)
        self._status.emit(status)

    def caption_updated(self, update: CaptionUpdate) -> None:
        if update.source_id == DICTATION:  # typed, never a caption (0073)
            if self.dictated is not None:
                self.dictated(update)
            return
        self.desktop.feed.receive(update)  # queued to the Qt thread

    def pace_changed(self, live_interval_min: float | None) -> None:
        if self.pipeline is not None:
            self.pipeline.set_pace_hint(live_interval_min)
        self._pace.emit(live_interval_min)

    def minutes_changed(self, used: float, left: float | None) -> None:
        self._minutes.emit(used, left)

    def notice(self, code: str) -> None:
        log.info("notice %s", code)
        self._notice.emit(code)

    def caption_failed(self) -> None:
        self._failed.emit()  # queued after the captions before it

    def connection_stalled(self, stalled: bool) -> None:
        self._stalled.emit(stalled)

    def rechecked(self, result: RecheckResult) -> None:
        log.info("recheck %s", result.outcome.value)  # never the line
        self.desktop.looks_wrong.receive(result)  # queued to the Qt thread

    def plan_changed(self, plan: protocol.PlanState) -> None:
        log.info("plan %s (%s, %s)", plan.tier, plan.source, plan.status)
        self._plan.emit(plan)

    @Slot(object)
    def _show_plan(self, plan: protocol.PlanState) -> None:
        """The plan as its line. A `plan` message that lowers the tier while
        a listening session holding Plus is open says Plus ends with the
        session: the session keeps its tier until it ends (protocol.md,
        `plan`). `welcome`'s plan is the session's own, and `limit_reached`'s
        comes as it ends, so they're said as they are (polyglotic-hq 237)."""
        from polyglotic_desktop.connection.protocol import Plan

        self._last_plan = plan_shown(plan)
        held = self._held if isinstance(plan, Plan) else None
        self.plan_shown.emit(plan_line(self._last_plan, held))

    @Slot(object)
    def _show_pace(self, live_interval_min: float | None) -> None:
        busy = live_interval_min is not None
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    @Slot(object)
    def _show_status(self, status: Status) -> None:
        from polyglotic_desktop.connection.reconnect import StopReason

        shown = self.desktop.connection
        state, retry_in = connection_state(status, shown)
        why = unreachable_shown(status, shown, self.desktop.unreachable)
        self.desktop.set_connection(state, retry_in, why)
        self._follow_held(status)
        if status.source_fields is not None:  # a listening session's `welcome`
            self.spoken_per_source.emit("spoken_language" in status.source_fields)
        if status.cohort is not None:  # any session's `welcome`
            self.cohort_seen.emit(status.cohort)
        if self.account is not None and state is ConnectionState.SIGN_IN_NEEDED:
            self.account.set_signed_in(False)
        if self.account is not None and status.account_id is not None:
            self.account.show_account(status.account_id)
        if status.stopped is StopReason.UPDATE_REQUIRED and self.updates is not None:
            self.updates.update_now(self.update_found.emit)  # straight to the updater

    def _follow_held(self, status: Status) -> None:
        """The listening session's tier, from its `welcome`, until it ends;
        when it ends, the last plan's own line - unless the account signed
        out, whose plan isn't shown any more."""
        from polyglotic_desktop.connection.reconnect import StopReason
        from polyglotic_desktop.connection.session import SessionState

        if status.stopped is StopReason.SIGN_IN_NEEDED:
            self._held = self._last_plan = None
            return
        if status.state is SessionState.LISTENING:
            self._held = status.tier
            return
        ended, self._held = self._held is not None, None
        if ended and self._last_plan is not None:
            self.plan_shown.emit(plan_line(self._last_plan))


def start_notice(set_aside: Path | None, taken_off: Sequence[str]) -> str:
    """What Home's banner says once as the app starts, if anything: a
    settings file that wasn't settings, set aside (polyglotic-hq 133), and
    saved languages taken off the list (DECISIONS.md #40; project 144)."""
    said = []
    if set_aside is not None:
        said.append(
            _tr_app(
                "Your settings couldn't be read, so they've been reset."
                " The old file is kept beside them as {name}."
            ).format(name=set_aside.name)
        )
    if taken_off:
        said.append(taken_off_note(taken_off))
    return " ".join(said)


def once_running(call: Callable[[], None]) -> None:
    """`call` as soon as the app's event loop runs - for a dialog the tray's
    Quit must be able to end: Qt ignores a quit before the loop runs, so the
    first run's sign-in, asked before it, stayed up and the app carried on
    without its tray (polyglotic-hq 133)."""
    QTimer.singleShot(0, call)


def captioning(value: AppSettings) -> bool:
    """Something is chosen to caption: apps, everything the PC plays, or
    the mic. A listening session is open only then - until the learner
    picks (the first run starts paused, polyglotic-hq DECISIONS.md #25) it
    would hold one of the account's places on the server for nothing
    (project 051's note; 061). Learning syncs in sync sessions meanwhile."""
    return value.source_chosen or value.caption_mic


def listen_then_sync(
    connection: Connection,
    listen: Callable[[], None],
    value: AppSettings,
    sample: bool = False,
) -> bool:
    """Listening first - if something is chosen to caption and it isn't
    already - then `start`, which, with a listening session open, opens no
    sync session: the listening session sends what waits and syncs
    learning itself. The other way round, the start-up sync's `hello`
    could already be out when listening began, and with another PC of the
    account listening the server would count three sessions - one refused
    `too_many_sessions` (polyglotic-hq project 042, Low 9). `start` still
    runs: it clears a stop left by signing out, and with nothing chosen it
    syncs. The sample (`sample`) is something to caption too. Whether a
    listening session is open."""
    if (captioning(value) or sample) and connection.listening is None:
        listen()
    connection.start()
    return connection.listening is not None


NO_SESSION = (ConnectionState.STOPPED, ConnectionState.NOT_CONNECTED)
"""The states the app's own stop leaves: nothing was chosen to caption."""


def follow_choice(
    connection: Connection,
    value: AppSettings,
    listen: Callable[[], None],
    desktop: DesktopApp | None = None,
    sample: bool = False,
    dictating: bool = False,
) -> None:
    """A setting changed: listening once something is chosen to caption -
    or while the sample is on (`sample`, polyglotic-hq 176), or while
    dictation needs a session (`dictating`: a hold under way, or one
    answered in the last minute - decision 0073) - and not once nothing
    is - what waits then goes in a sync session. A session just
    opened says Connecting at once (`desktop`): Home said "Stopped" - the
    last session's end - until the new one's first word (polyglotic-hq
    145)."""
    wanted = captioning(value) or sample or dictating
    if wanted and connection.listening is None:
        opened = listen_then_sync(connection, listen, value, sample or dictating)
        if opened and desktop is not None and desktop.connection in NO_SESSION:
            desktop.set_connection(ConnectionState.CONNECTING)
    elif not wanted and connection.listening is not None:
        connection.stop_listening()


def plus_is_back(connection: ConnectionState | None, line: PlanLine) -> bool:
    """Stopped because Plus ended (4009), and a plan with Plus arrives - a
    code redeemed, or Plus bought: listening starts again by itself
    (polyglotic-hq 185)."""
    return connection is ConnectionState.PLUS_ENDED and line.has_plus


class NotAgreed(Exception):
    """The first screen closed without the yes: under 16, or no to the
    tester agreement."""


@dataclass(frozen=True)
class FirstChoice:
    """What the first screen chose: what's shared, and the yes."""

    choices: tuple[bool, bool, bool]
    agreement: Agreement | None


@dataclass(frozen=True)
class FirstRun:
    """What the first run's screens leave (`first_run`): the learner's
    tools for the language chosen, with their learning store (to close at
    the end); Your data's answer, if it was asked; and whether the code was
    asked - then it isn't again, over the window."""

    tools: LearningTools
    learning_store: BackgroundLearningStore
    first: FirstChoice | None
    code_asked: bool


def first_run(
    store: SettingsStore,
    learner: Callable[[bool], tuple[LearningTools, BackgroundLearningStore]],
    consent: ConsentChoice | None,
    code: Redeem | None,
    code_again: bool = False,
    windows_languages: Sequence[str] = (),
    kept: Callable[[str], bool] = lambda _: False,
) -> FirstRun:
    """At start, the first run's screens, one after another, each after the
    first with Back (polyglotic-hq 250, the user's F4; `ui.first_run`):

    1. Your data and the yes - the first run, or the tester agreement's new
       words (`agreement_needed`), with `consent`, the choices so far;
    2. the code, after that, when this PC isn't signed in (`code` given):
       the first run ends signed in, or signed out if it's closed. A later
       start signed out asks it over the window instead. `code_again`: this
       PC has signed in before, so its code works again (polyglotic-hq 288).

    No language and no level are asked (polyglotic-hq 293, decision 0085):
    the app opens for anyone, every language is chosen in Settings and on
    Learning, and words are estimated at a middle level until the learner
    sets theirs (Home's line asks, `HomePage.show_level_line`).
    `learner` builds the tools (English: True) for the language being
    learned, or until one is chosen a guess from Windows' display languages
    (`windows_languages`, in the user's order) and the learning data `kept`
    on this PC (`starting_language`). New settings translate into the first
    of Windows' languages that captions are translated into, else English
    (`own_targets`); saved ones are kept as they are.

    Each answer is kept on its own screen's Next, never on Back. Closing a
    screen goes on without its answer - except Your data's, which raises
    `NotAgreed` (polyglotic-hq 185, DECISIONS.md #88)."""
    new = not store.load()  # nothing saved yet: this PC's first start
    settings = Settings(store)
    own = own_targets(windows_languages)
    if new and own and (own[0],) != settings.value.targets:
        settings.update(targets=(own[0],))
    chosen = starting_language(
        settings.value.learning,
        learned_code(windows_languages[0]) if windows_languages else None,
        kept,
    )
    learning, learning_store = learner(chosen == "en")
    # the learner's theme, as the window will have it (`DesktopApp`): no
    # window yet to share its stylesheet
    theme.apply(settings.value.window_theme, settings.value.theme)
    sheet = style.stylesheet(window_theme())
    first: FirstChoice | None = None
    screens: dict[str, TextDialog] = {}
    answered = False
    """A screen before the code was asked."""
    code_asked = False

    def screen(key: str, make: Callable[[], TextDialog]) -> TextDialog:
        """The screen for `key`, made once: shown again, it has what was
        entered on it."""
        if key not in screens:
            screens[key] = make()
            screens[key].setStyleSheet(sheet)
        return screens[key]

    def ask_consent(back: bool) -> Answer:
        nonlocal first, answered
        answered = True
        tester = None if settings.value.cohort is None else is_tester(settings.value)
        shown = screen("consent", lambda: ConsentDialog(consent, tester=tester))
        assert isinstance(shown, ConsentDialog)
        result = asked(shown, shown.back, back)
        if result == BACK:
            return Answer.BACK
        if not result:  # closed, or Quit: no yes, no further
            return Answer.QUIT
        first = FirstChoice(shown.choices(), shown.agreement())
        return Answer.NEXT

    def ask_code(back: bool) -> Answer:
        nonlocal code_asked
        code_asked = True
        assert code is not None
        shown = screen("code", lambda: SignInDialog(code, again=code_again))
        assert isinstance(shown, SignInDialog)
        result = asked(shown, shown.back, back)
        return Answer.BACK if result == BACK else Answer.NEXT  # in, or signed out

    agreed = run_first_run(
        [
            Step("consent", lambda: agreement_needed(consent), ask_consent),
            Step("code", lambda: code is not None and answered, ask_code),
        ]
    )
    for shown in screens.values():
        shown.deleteLater()
    if not agreed:
        learning_store.close()  # no further
        raise NotAgreed
    return FirstRun(learning, learning_store, first, code_asked)


def sign_in_problem(result: RedeemResult) -> SignInFailed | None:
    """The connection's answer to an invite code, as the sign-in dialog
    shows it; None once signed in."""
    from polyglotic_desktop.connection.sign_in import (
        InviteNotValid,
        NotACode,
        PlusAlready,
        SignedIn,
        SignInAgain,
        SignOutFirst,
        SubscriptionEnded,
        TooManyAttempts,
    )

    if isinstance(result, SignedIn):
        return None
    if isinstance(result, NotACode):
        return SignInFailed(SignInProblem.NOT_A_CODE)
    if isinstance(result, InviteNotValid):
        return SignInFailed(SignInProblem.NOT_VALID)
    if isinstance(result, SubscriptionEnded):
        return SignInFailed(SignInProblem.SUBSCRIPTION_ENDED)
    if isinstance(result, TooManyAttempts):
        return SignInFailed(SignInProblem.TOO_MANY_ATTEMPTS, result.retry_after)
    if isinstance(result, PlusAlready):
        return SignInFailed(SignInProblem.PLUS_ALREADY)
    if isinstance(result, SignInAgain):
        return SignInFailed(SignInProblem.SIGN_IN_AGAIN)
    if isinstance(result, SignOutFirst):
        return SignInFailed(SignInProblem.SIGN_OUT_FIRST)
    return SignInFailed(SignInProblem.UNREACHABLE, unreachable=result.unreachable)


class SignedInCohort:
    """The cohort a code signed in with - the redeem answer's - handed from
    the sign-in thread to the interface's: the account's test group is known
    from the first minute, so an alpha tester's "Report a problem" and
    diagnostics don't wait for the first session's `welcome` (polyglotic-hq
    279). `answered` runs on the sign-in thread; the dialog's own answer
    reaches the interface's thread after it, and `take` is read there."""

    def __init__(self) -> None:
        self._cohort: str | None = None

    def answered(self, result: RedeemResult) -> SignInFailed | None:
        """`result` as the sign-in dialog shows it (`sign_in_problem`), its
        cohort kept when it signed in."""
        from polyglotic_desktop.connection.sign_in import SignedIn

        if isinstance(result, SignedIn):
            self._cohort = result.cohort
        return sign_in_problem(result)

    def take(self) -> str | None:
        """The cohort the last code signed in with, once: None if no code
        has signed in since the last take."""
        cohort, self._cohort = self._cohort, None
        return cohort


def entry_text(tools: LearningTools, entry_id: EntryId) -> EntryText | None:
    """What a word saved on another PC keeps here, from this PC's dictionary."""
    entry = tools.entry(entry_id)
    if entry is None:
        return None
    meaning = short_meaning([entry])
    return EntryText(entry.headword, entry.traditional, entry.reading, meaning)


class QtExchange(QObject):
    """The exchange's listener: statuses and saved words from the server,
    and the server's "deleted", arrive on a session's thread and are
    applied to the learner's vocabulary on the Qt thread (it's single-
    threaded), without being sent back."""

    _arrived = Signal(object)
    _deleted = Signal()

    def __init__(self, tools: LearningTools, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.tools = tools
        self.delete_here = False
        """Set when the user also asked to delete the data on this PC."""
        self._arrived.connect(self._apply, Qt.ConnectionType.QueuedConnection)
        self._deleted.connect(self._delete, Qt.ConnectionType.QueuedConnection)

    def learning_arrived(self, events: Sequence[LearningEvent]) -> None:
        self._arrived.emit(list(events))

    def learning_deleted(self) -> None:
        self._deleted.emit()

    @Slot(object)
    def _apply(self, events: list[LearningEvent]) -> None:
        changed = self.tools.vocabulary.apply_from_server(
            events, lambda entry_id: entry_text(self.tools, entry_id)
        )
        log.info("learning from the server: %d change(s) applied", changed)

    @Slot()
    def _delete(self) -> None:
        log.info("learning data deleted on the server")
        if self.delete_here:
            self.delete_here = False
            self.tools.vocabulary.delete_learning_data()
            log.info("learning data deleted on this PC")


class QtFeedback(QObject):
    """The feedback sender's outcomes: they come on its thread and show on
    Home on the Qt thread. `just_sent`: the report the user sent this time."""

    _outcome = Signal(str, str)

    def __init__(self, desktop: DesktopApp) -> None:
        super().__init__(desktop)
        self.desktop = desktop
        self.just_sent: str | None = None
        self._outcome.connect(self._show, Qt.ConnectionType.QueuedConnection)

    def outcome(self, report: Report, outcome: Outcome) -> None:
        self._outcome.emit(report.id, outcome.value)

    def outcome_of(self, report_id: str, outcome: Outcome) -> None:
        """A problem report's outcome (polyglotic-hq 275), from its sender's thread."""
        self._outcome.emit(report_id, outcome.value)

    @Slot(str, str)
    def _show(self, report_id: str, outcome: str) -> None:
        self.desktop.show_feedback(outcome, report_id == self.just_sent)


def new_report(
    kind: ReportKind,
    text: str,
    reply_to: str | None,
    attached: str | None,
    app: AppInfo,
    session_id: str | None,
) -> Report:
    """A report as the user sent it now, with what goes with every one."""
    from polyglotic_desktop.connection import protocol

    return Report(
        id=str(uuid.uuid4()),
        at=protocol.at(datetime.now(UTC)),
        kind=kind,
        text=text,
        reply_to=reply_to,
        log=attached,
        app_version=app.app_version,
        os=app.os,
        os_version=app.os_version,
        session_id=session_id,
    )


def feedback_versions(app: AppInfo) -> str:
    """This copy's versions, as the feedback form says they're sent - in
    the interface language's punctuation (polyglotic-hq 235: 223 saw an
    ASCII comma among the Chinese form's own)."""
    #: The feedback form's "Also sent: ...": the app's version, Windows' name
    #: (windows-11) and its version number (10.0.26200) - keep them as they are
    return _tr_app("Polyglotic {version}, {os} ({os_version})").format(
        version=app.app_version, os=app.os, os_version=app.os_version
    )


TESTER_COHORTS = frozenset({"alpha"})
"""Cohorts whose testers get "Report a problem" with everything attached,
and diagnostics always on (polyglotic-hq 275; decision 0067). The server
refuses captions and audio from anyone else (its decision 0055)."""


def is_tester(settings: AppSettings) -> bool:
    """Whether the account signed in is an alpha tester's, as last said."""
    return settings.cohort in TESTER_COHORTS


def diagnostics_on_for_testers(exchange: DataExchange) -> bool:
    """An alpha tester's crash reports and usage statistics, on (the user,
    2026-11-11: content-free diagnostics always on for alpha testers; the
    consent screen says so). Word counts stay as chosen. Nothing before the
    first run's choice. True if it changed anything."""
    current = exchange.consent
    if current is None or (current.usage and current.crashes):
        return False
    exchange.choose_consent(True, True, current.exposures)
    log.info("an alpha tester: crash reports and usage statistics on")
    return True


def cohort_known(
    cohort: str,
    settings: Settings,
    exchange: DataExchange,
    reporting: Callable[[bool], None],
) -> None:
    """The account's test group, from a code's redeem answer or a session's
    `welcome`: kept for the next start (the menu's "Report a problem" works
    before a session opens), the caption windows' "Report a problem" shown
    to a tester (`reporting`), and an alpha tester's diagnostics on
    (polyglotic-hq 275, 279)."""
    if settings.value.cohort != cohort:
        settings.update(cohort=cohort)
    tester = is_tester(settings.value)
    reporting(tester)
    if tester:
        diagnostics_on_for_testers(exchange)


def report_facts(
    app: AppInfo,
    channel: str,
    speech: Sequence[SpeechPart],
    apps_one_by_one: str | None = None,
) -> dict[str, object]:
    """The app, Windows and the audio devices, for a problem report: no
    caption text, no app's name - each source by its id and category.
    `apps_one_by_one`: the log's line on capturing apps one by one - the
    build, whether it was tried, how it went (decision 0076)."""
    screens = [
        {
            "scale": screen.devicePixelRatio(),
            "width": screen.geometry().width(),
            "height": screen.geometry().height(),
        }
        for screen in QGuiApplication.screens()
    ]
    facts: dict[str, object] = {
        "app": {
            "version": app.app_version,
            "channel": channel,
            "installed": installed(),
            "interface_language": QLocale().name(),
            "qt": qVersion(),
        },
        "windows": {
            "os": app.os,
            "version": app.os_version,
            "screens": screens,
            **({"apps_one_by_one": apps_one_by_one} if apps_one_by_one else {}),
        },
        "sources": [
            {"id": part.source_id, "category": part.category.value} for part in speech
        ],
    }
    try:
        from polyglotic_desktop.platform.windows.devices import (
            Flow,
            active_devices,
            default_device,
        )

        facts["audio_devices"] = {
            flow.name.lower(): {
                "default": getattr(default_device(flow), "name", None),
                "active": [d.name for d in active_devices(flow)],
            }
            for flow in Flow
        }
    except (ImportError, OSError) as problem:  # no Core Audio here
        facts["audio_devices"] = {"unavailable": type(problem).__name__}
    return facts


def _json_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def problem_report_parts(
    log_text: str | None,
    settings: dict[str, object],
    facts: dict[str, object],
    captions: list[dict[str, object]],
    speech: Sequence[SpeechPart],
    names: dict[str, str],
    check_result: str | None,
) -> list[Part]:
    """What "Report a problem" offers, each part with its size and what
    Look shows: exactly what goes. A part with nothing in it isn't offered."""
    labels = part_labels()
    parts = []
    if check_result:
        parts.append(
            Part("check", labels["check"], len(check_result), lambda: check_result)
        )
    if log_text is not None:
        parts.append(
            Part("log", labels["log"], len(log_text.encode("utf-8")), lambda: log_text)
        )
    pretty = partial(json.dumps, ensure_ascii=False, indent=2)
    parts.append(
        Part(
            "settings",
            labels["settings"],
            _json_size(settings),
            lambda: pretty(settings),
        )
    )
    parts.append(
        Part("facts", labels["facts"], _json_size(facts), lambda: pretty(facts))
    )
    if captions:
        parts.append(
            Part(
                "captions",
                labels["captions"],
                _json_size(captions),
                lambda: captions_look(captions),
                captions_detail(len(captions)),
            )
        )
    said = {str(c["caption_id"]): str(c["original"]) for c in captions}
    for part in speech:
        clips = [(str(c.caption_id), c.end - c.start) for c in part.clips]
        parts.append(
            Part(
                f"speech:{part.source_id}",
                speech_label(names.get(part.source_id, part.category.value)),
                part.size,
                partial(speech_look, clips, said),
                speech_detail(part.seconds),
                others_voices=part.others_voices,
            )
        )
    return parts


def ask_for_feedback(
    kind: ReportKind,
    logs: Path,
    app: AppInfo,
    session_id: str | None,
    waiting: WaitingReports,
    parent: QWidget | None = None,
    check_result: str | None = None,
) -> Report | None:
    """The feedback form; the report kept to send if the user sent it.
    `check_result` is Help's "no captions?" check, added to the text."""
    dialog = FeedbackDialog(
        kind,
        lambda: read_log(logs),
        feedback_versions(app),
        session_id is not None,
        parent,
        check_result,
    )
    if not dialog.exec():
        return None
    report = new_report(*dialog.report(), app, session_id)
    waiting.add(report)
    log.info("a %s report kept to send", report.kind)
    return report


def share_finished_days(vocabulary: Vocabulary, exchange: DataExchange) -> None:
    """Finished UTC days' exposure counts, handed over once: kept to send
    only with the learner's opt-in, dropped otherwise."""
    days = vocabulary.take_finished_exposure_days(datetime.now(UTC).date())
    if days:
        exchange.exposures(days)


@dataclass(frozen=True)
class SourcePlan:
    """What to capture: the apps picked that are open (each by process id -
    its name stays on this PC), everything the PC plays (`whole_system`),
    or neither (nothing picked yet, or no app picked is open); everything
    else the PC plays beside the one app picked (`everything_else`): that
    app left out while it's open, else the whole system's audio; and the
    mic."""

    apps: tuple[tuple[int, str, SourceCategory], ...]
    whole_system: bool
    mic: bool
    everything_else: bool = False


def plan_sources(
    value: AppSettings, apps: list[PlayingApp], per_app: bool
) -> SourcePlan:
    """The sources the settings ask for. Nothing until the learner picks
    what to caption (the first run starts paused: polyglotic-hq
    DECISIONS.md #25). Everything the PC plays when they chose it, or
    picked apps Windows can't capture on their own (Windows 10); otherwise
    each app picked that's open - one that isn't joins when it opens -
    and everything else beside the one app, if it's on. The mic follows
    its own switch.

    Of several processes of one app, the same one each time, whatever
    order Windows lists them in: one playing before one that isn't, then
    the lowest process id - a different one would restart the source."""
    if not value.source_chosen:
        return SourcePlan((), False, value.caption_mic)
    if value.whole_system or not per_app:
        return SourcePlan((), True, value.caption_mic)
    found = []
    for name in value.apps:
        app = min(
            (a for a in apps if a.name == name),
            key=lambda a: (not a.playing, a.process_id),
            default=None,
        )
        if app is not None:
            found.append((app.process_id, app.name, app.category))
    return SourcePlan(
        tuple(found), False, value.caption_mic, value.captions_everything_else
    )


TRIAL_CHECK_MS = 1000
"""How often a trial of capturing apps one by one is asked how it went."""


def apps_one_by_one(
    support: AppCaptureSupport, fell_back: Mapping[str, str], here: Mapping[str, str]
) -> bool:
    """Whether apps are captioned one by one on this PC (decision 0076):
    where Windows promises it; where it may (Windows 10 version 2004 and
    later) unless it failed here before (`fell_back`: the Windows build and
    the app's version it failed with, and why) and both are as they were
    (`here`) - a Windows update or an app update tries again; never where
    it can't (everything the PC plays)."""
    if support is AppCaptureSupport.YES:
        return True
    if support is AppCaptureSupport.NO:
        return False
    return not fell_back or any(fell_back.get(k) != v for k, v in here.items())


def app_capture_line(
    support: AppCaptureSupport,
    build: str,
    on: bool,
    outcome: TrialOutcome | None = None,
    fell_back: Mapping[str, str] | None = None,
) -> str:
    """The log's line on capturing apps one by one (decision 0076):
    Windows' build, whether it was tried, and whether it worked or why not
    - Windows' code, never an app's name. Content-free: it says what the
    first Windows 10 tester's PC did."""
    start = f"capturing apps one by one: Windows build {build}, "
    if support is AppCaptureSupport.YES:
        return start + "promised"
    if support is AppCaptureSupport.NO:
        return start + "not tried (Windows before version 2004)"
    if outcome is not None:
        if outcome.worked:
            return start + "tried: it worked"
        return start + f"tried: it failed ({outcome.why}), everything the PC plays now"
    if on:
        return start + "trying"
    why = (fell_back or {}).get("why", "")
    return start + f"not tried: it failed here before ({why})"


class AppsOneByOne(QObject):
    """Whether apps are captioned one by one on this PC (`on`) - and,
    where Windows doesn't promise it (Windows 10 version 2004 to 22H2:
    decision 0076), trying it: the captures tell `trial` what they find.
    If it fails, it's everything the PC plays from then on, remembered in
    the settings for this Windows update and this version of the app (an
    update of either tries again, as does `try_again`); `changed` says so.
    `line` is the log's line on it, the latest."""

    changed = Signal()

    def __init__(
        self,
        support: AppCaptureSupport,
        settings: Settings,
        build: str,
        app_version: str,
        new_trial: Callable[[], AppCaptureTrial],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.support, self._settings, self._new_trial = support, settings, new_trial
        self._build = build
        self._here = {"windows": build, "app": app_version}
        fell_back = settings.value.app_capture_fell_back
        self.on = apps_one_by_one(support, fell_back, self._here)
        self.trial: AppCaptureTrial | None = None
        self._watch = QTimer(self, interval=TRIAL_CHECK_MS)
        self._watch.timeout.connect(self.check)
        if self.on and support is AppCaptureSupport.TRY:
            self._start_trial()
        self._say(app_capture_line(support, build, self.on, None, fell_back))

    @property
    def fell_back(self) -> bool:
        """Tried here, and Windows couldn't capture one app alone."""
        return self.support is AppCaptureSupport.TRY and not self.on

    def _start_trial(self) -> None:
        self.trial = self._new_trial()
        self._watch.start()

    def _say(self, line: str) -> None:
        self.line = line
        log.info("%s", line)

    def check(self) -> None:
        """How the trial went, once a capture has shown: it worked (said
        in the log), or everything the PC plays from now on."""
        outcome = self.trial.outcome if self.trial is not None else None
        if outcome is None:
            return
        self._watch.stop()
        self._say(app_capture_line(self.support, self._build, True, outcome))
        if outcome.worked:
            return
        self.on, self.trial = False, None
        self.changed.emit()
        self._settings.update(app_capture_fell_back={**self._here, "why": outcome.why})

    def try_again(self) -> None:
        """Apps one by one again, after it failed here: tried afresh."""
        if not self.fell_back:
            return
        self.on = True
        self._start_trial()
        self._say(app_capture_line(self.support, self._build, True))
        self.changed.emit()
        self._settings.update(app_capture_fell_back={})


def fell_back_text() -> str:
    """What the learner is told, once, when capturing apps one by one
    failed on this PC (decision 0076)."""
    return _tr_app(
        "Windows on this PC couldn't caption one app alone, so Polyglotic"
        " captions everything the PC plays. You can try apps again on Home."
    )


class Sources:
    """The pipeline's sources, following the settings: each app picked
    (with everything else the PC plays beside one), or everything the PC
    plays, and the mic - each a source of its own, with its own speech
    detection and timing.

    A change starts and stops only what changed: an app picked closing, or
    opening again, leaves the other sources as they were (speech in
    progress included). Each app keeps one source id while the app runs -
    `app-1`, `app-2`, ... in the order they were first captured, never its
    name (protocol.md, `source.id`); `ids` maps the app's name to it, on
    this PC only. `on_change` is told, after each change, each app's
    source id, name and what it's called on screen (its public name if
    it's a known app) - for its captions' labels; `on_capture`, what is
    captured now - the mode, how many apps, the mic - for the listening
    session's usage statistics (polyglotic-hq project 134).

    **Everything else** (polyglotic-hq DECISIONS.md #59) is captured
    leaving its one app out (`everything_else_capture`, by the app's
    process id), so nothing is heard twice; while that app isn't open, it
    is everything the PC plays - and it restarts, leaving the app out,
    when the app opens (or closes again).

    **The app's own sound** (a looked-up word said aloud, polyglotic-hq
    286): everything the PC plays, everything else and the mic can hear it,
    so they're added as hearing the app (`hears_the_app`) and are silent
    while it plays (`SpeechPipeline.hush`); an app on its own never hears
    it, nor does the sample.

    **Nothing is captured while signed out** (`signed_in`): audio is taken
    only to serve the learner, and a signed-out app serves nothing - it
    starts on signing in (polyglotic-hq 137; before, an app added on a
    first run left at "Not signed in" was captured and run through speech
    detection, 133).

    **The sample** (polyglotic-hq 176): while it's on (`play_sample`) -
    and nothing else is chosen - the recording `sample_capture` makes is a
    source of its own (SAMPLE), started again each time it's turned on.
    Played to its end (`sample_done`), `end_sample` turns it off and keeps
    its window for lookups (`sample_kept`) until an app is chosen, or it's
    tried again or closed (polyglotic-hq 208)."""

    def __init__(
        self,
        pipeline: SpeechPipeline,
        apps: AppList,
        per_app: bool,
        app_capture: Callable[[int, str], AudioCapture],
        system_capture: Callable[[], AudioCapture],
        mic_capture: Callable[[], AudioCapture],
        on_change: Callable[[dict[SourceId, tuple[str, str]]], None] | None = None,
        on_capture: Callable[[Capture], None] | None = None,
        signed_in: bool = True,
        *,
        everything_else_capture: Callable[[int], AudioCapture],
        sample_capture: Callable[[], AudioCapture | None] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.signed_in = signed_in
        self._value: AppSettings | None = None  # the settings last followed
        self.on_change = on_change
        self.on_capture = on_capture
        self.apps = apps
        self.per_app = per_app
        self._app_capture = app_capture
        self._system_capture = system_capture
        self._mic_capture = mic_capture
        self._everything_else_capture = everything_else_capture
        self._sample_capture = sample_capture
        self.sample_on = False
        self.sample_kept = False  # ended, its window kept for lookups (208)
        self._sample: AudioCapture | None = None  # the one playing, if any
        self._samples = 0  # times turned on: each is a capture of its own
        self.plan: SourcePlan | None = None
        self.ids: dict[str, SourceId] = {}
        self._titles: dict[str, str] = {}  # an app's name -> on screen
        self._known: dict[str, str | None] = {}  # -> its public name, if known
        self._running: dict[SourceId, tuple[object, ...]] = {}
        self._categories: dict[SourceId, SourceCategory] = {}
        self._buffers: dict[SourceId, AudioBuffer] = {}
        self._reference: AudioBuffer | None = None  # what the PC played, for the mic

    def category_of(self, name: str) -> SourceCategory | None:
        """The category of the app called `name`, if it is captured now."""
        apps = self.plan.apps if self.plan is not None else ()
        return next((c for _, n, c in apps if n == name), None)

    def category_of_source(self, source_id: SourceId) -> SourceCategory:
        """The category of the source captured as `source_id` (the last it
        was captured as), else `other`."""
        return self._categories.get(source_id, SourceCategory.OTHER)

    def app_id(self, name: str) -> SourceId:
        """The source id of the app called `name`: the same each time it's
        captured while Polyglotic runs."""
        if name not in self.ids:
            self.ids[name] = SourceId(f"app-{len(self.ids) + 1}")
        return self.ids[name]

    def shown(self) -> dict[SourceId, tuple[str, str]]:
        """Each app captured since Polyglotic started: its source id ->
        (its name, what it's called on screen)."""
        return {
            source_id: (name, self._titles.get(name, name))
            for name, source_id in self.ids.items()
        }

    @property
    def sample_shown(self) -> bool:
        """The sample's window shows: while it plays, and after its end."""
        return self.sample_on or self.sample_kept

    @property
    def sample_done(self) -> bool:
        """The sample has played to its end and the speech detector has
        nothing of it under way: its last sentence is finished (each sample
        ends in silence - tests/test_sample.py). Time to end it."""
        capture = self._sample
        return (
            self.sample_on
            and capture is not None
            and capture.capturing is None
            and SAMPLE not in self.pipeline.hearing()
        )

    def play_sample(self, on: bool) -> None:
        """The sample on - from its start - or off (its window too)."""
        changed = self.sample_kept or on != self.sample_on
        self.sample_kept = False
        if not changed:
            return
        self.sample_on = on
        self._samples += on
        if self._value is not None:
            self.follow(self._value, again=True)

    def end_sample(self) -> None:
        """The sample has played to its end: off, its window kept for
        lookups (polyglotic-hq 208, 203's option B)."""
        if self.sample_on:
            self.play_sample(False)
            self.sample_kept = True

    def set_signed_in(self, signed_in: bool) -> None:
        """Signed in (capture follows the settings) or out (nothing is
        captured). Signed out, the sample stops and its window goes, as an
        app's does: it isn't in the plan, so an unchanged plan left it
        playing aloud, captioned by nothing (polyglotic-hq 223)."""
        if signed_in != self.signed_in:
            self.signed_in = signed_in
            gone = not signed_in and self.sample_shown
            if gone:
                self.sample_on = self.sample_kept = False
            if self._value is not None:
                self.follow(self._value, again=gone)

    def follow(self, value: AppSettings, again: bool = False) -> None:
        """Capture as `value` says - `again`: even if its plan is the same
        (the sample turned on or off)."""
        self._value = value
        if value.source_chosen and self.sample_shown:
            self.sample_on = False  # an app (or the PC) chosen: the sample's done
            self.sample_kept = False
            again = True
        wants_apps = self.per_app and not value.whole_system and value.apps
        apps = self.apps.playing_apps() if wants_apps and self.signed_in else []
        plan = (
            plan_sources(value, apps, self.per_app)
            if self.signed_in
            else SourcePlan((), False, False)
        )
        for app in apps:
            self._titles[app.name] = app.title
            self._known[app.name] = app.known_name
        if plan == self.plan and not again:
            return
        self.plan = plan
        if self.on_capture is not None:
            self.on_capture(
                capture_of(
                    value.source_chosen,
                    plan.whole_system,
                    len(plan.apps),
                    plan.mic,
                    plan.everything_else,
                )
            )
        # what each source captures: a change of it restarts the source
        wanted: dict[SourceId, tuple[object, ...]] = {}
        apps_wanted: dict[SourceId, tuple[int, str, SourceCategory]] = {}
        for process_id, name, category in plan.apps:
            source_id = self.app_id(name)
            wanted[source_id] = ("app", process_id, name)
            apps_wanted[source_id] = (process_id, name, category)
        if plan.whole_system:
            wanted[WHOLE_SYSTEM] = ("system",)
        # everything else leaves its one app out while it's open (by process id)
        left_out = plan.apps[0][0] if plan.everything_else and plan.apps else None
        if plan.everything_else:
            wanted[EVERYTHING_ELSE] = ("everything_else", left_out)
        if self.sample_on and self.signed_in and self._sample_capture is not None:
            wanted[SAMPLE] = ("sample", self._samples)
        if plan.mic:
            # the mic is checked for bleed against what the PC played
            # (decision 0004): the whole system's own audio, or a reference
            wanted[MIC] = ("mic", plan.whole_system)
        for source_id in [
            s for s in self._running if wanted.get(s) != self._running[s]
        ]:
            self.pipeline.remove_source(source_id)
            del self._running[source_id]
            self._buffers.pop(source_id, None)
            if source_id == SAMPLE:
                self._sample = None
        if MIC not in self._running and self._reference is not None:
            self.pipeline.remove_reference(self._reference)
            self._reference = None
        for source_id, what in wanted.items():
            if source_id in self._running:
                continue
            if source_id in apps_wanted:
                process_id, name, category = apps_wanted[source_id]
                # its public name, if it's a known app: for the session's
                # usage statistics only, with consent (DECISIONS.md #30)
                known = self._known.get(name)
                source = Source(
                    source_id, category, known_app_id(known) if known else None
                )
                capture = self._app_capture(process_id, name)
                self._buffers[source_id] = self.pipeline.add_source(source, capture)
                self._categories[source_id] = category
            elif source_id == SAMPLE:
                assert self._sample_capture is not None
                sample = self._sample_capture()
                if sample is None:  # none in the language learned
                    continue
                self._sample = sample
                source = Source(SAMPLE, SourceCategory.OTHER)
                self._categories[SAMPLE] = SourceCategory.OTHER
                self._buffers[SAMPLE] = self.pipeline.add_source(source, sample)
            elif source_id == WHOLE_SYSTEM:
                source = Source(WHOLE_SYSTEM, SourceCategory.SYSTEM)
                self._categories[WHOLE_SYSTEM] = SourceCategory.SYSTEM
                capture = self._system_capture()
                self._buffers[WHOLE_SYSTEM] = self.pipeline.add_source(
                    source, capture, hears_the_app=True
                )
            elif source_id == EVERYTHING_ELSE:
                source = Source(EVERYTHING_ELSE, SourceCategory.SYSTEM)
                self._categories[EVERYTHING_ELSE] = SourceCategory.SYSTEM
                capture = (
                    self._system_capture()
                    if left_out is None
                    else self._everything_else_capture(left_out)
                )
                self._buffers[EVERYTHING_ELSE] = self.pipeline.add_source(
                    source, capture, hears_the_app=True
                )
            else:
                reference = self._buffers.get(WHOLE_SYSTEM)
                if reference is None:
                    self._reference = self.pipeline.add_reference(
                        self._system_capture()
                    )
                    reference = self._reference
                mic = Source(MIC, SourceCategory.MIC)
                self.pipeline.add_source(
                    mic, self._mic_capture(), reference, hears_the_app=True
                )
            self._running[source_id] = what
        if self.on_change is not None:
            self.on_change(self.shown())
        log.info(
            "capturing %s%s%s",
            f"{len(plan.apps)} app(s)" if not plan.whole_system else "everything",
            " and everything else" if plan.everything_else else "",
            " and the mic" if plan.mic else "",
        )


def start_interface_language(
    app: QApplication, store: SettingsStore
) -> list[QTranslator]:
    """The interface's language - the setting, else Windows', else English -
    installed before the first window or question (decision 0034): its
    translations, children of `app` for as long as it runs."""
    language = interface_language.pick(
        Settings(store).value.interface_language, interface_language.windows_languages()
    )
    translators = interface_language.install(app, language)
    app.setProperty("interface_language", language)  # interface_language.in_use
    style.use_interface_language(language)  # its script's font first
    log.info("interface: %s (%d translation files)", language, len(translators))
    return translators


def sample_language(value: AppSettings, tools: LearningTools | None) -> str | None:
    """The language Home's sample is in: the one being learned - or, until
    one is chosen (the first run asks none: polyglotic-hq 293), the one
    whose dictionary runs."""
    if value.learning is not None or tools is None:
        return value.learning
    return tools.language


def _learning_settings(value: AppSettings) -> tuple[object, ...]:
    """What Learning's page shows from the settings."""
    return (value.learning_languages, value.word_introductions)


def learning_file(data: Path, english: bool) -> Path:
    """Where a language's learning data is kept: each its own file, so
    switching back finds it as it was."""
    return data / ("learning-en.sqlite" if english else "learning.sqlite")


def kept_level(data: Path, code: str) -> LevelCurve | None:
    """A full dictionary's level as it was kept beside its learning data
    (decision 0048) - read, never opened: Learning shows the level of a
    language not in use (polyglotic-hq 262). None when there's none."""
    if code not in FULL:
        return None
    stored = read_level_file(learning_file(data, code == "en"))
    return LevelCurve(stored.scheme, stored.midpoint) if stored else None


def learner_dictionary(english: bool) -> str:
    """The learner's dictionary - its file's name, and the start of every
    entry ID in their learning data: CC-CEDICT for a Chinese learner,
    ECDICT for an English one."""
    return "ecdict" if english else "cedict"


def packs_folder(dictionaries: Path, data: Path) -> Path:
    """Where the dictionary packs are kept (decision 0089): an installed
    copy's with the learner's data (`data`), never in the install folder -
    an update replaces that whole folder, and the Microsoft Store's can't
    be written - so a pack stays through every update; from source, in
    `dictionaries` (`build/dictionaries`), where `tools.dictionaries.packs`
    writes them."""
    if installed():
        return data / "dictionaries"
    return dictionaries / "packs"


def basic_dictionaries(folder: Path, meanings: str) -> dict[str, BasicDictionary]:
    """The basic dictionary packs in `folder` (decision 0035), by caption
    language, with meanings in `meanings` ("en", or "zh" for the
    `-zh.sqlite` files), from `packs_folder`. Only with the developer
    switch `--basic-dictionaries`: their word splits aren't in the
    installer (DECISIONS #65 in polyglotic-hq). A file that can't be
    read (cut off, an older format) is left out, said in the log: its
    language is looked up as before, and the app still starts."""
    found = {}
    for path in sorted(folder.glob("*.sqlite")):
        if path.stem.endswith("-zh") != (meanings == "zh"):
            continue
        try:
            file = SqliteDictionary(path)
        except (DictionaryFormatError, OSError) as e:
            log.warning("Basic dictionary %s left out: %s", path.name, type(e).__name__)
            continue
        language = file.info.get("language", "")
        if file.info.get("tier") != "basic" or not language:
            file.close()
            continue
        split = JapaneseSplit() if language == "ja" else SpacedSplit(language)
        found[language] = BasicDictionary(file, split, language)
    log.info("Basic dictionaries: %s", ", ".join(sorted(found)) or "none")
    return found


def learner_tools(
    dictionaries: Path,
    english: bool,
    data: Path,
    basic: Mapping[str, BasicDictionary] | None = None,
) -> tuple[LearningTools, BackgroundLearningStore]:
    """The learner's vocabulary and dictionary: CC-CEDICT for a Chinese
    learner, ECDICT for an English one. Each language keeps its own
    learning data, so switching back finds it as it was. With it, the
    learning store, for closing at the end.

    A dictionary file that's missing or can't be read doesn't stop the
    start (polyglotic-hq 199): it's left out, said in the log, and the
    tools' `dictionary_problem` says why - captions run, and lookups say
    what's wrong. One that fails a query later (damaged in the middle)
    goes out then, and the tools' `dictionary_out` says so. The learner's
    data is kept as it is.

    A learning data file that can't be read doesn't stop the start either
    (polyglotic-hq 206): it's set aside, kept, and a new one started
    (`open_learning_store`). One from a newer app still does. One found
    damaged later - a save failing - is set aside then, nothing more is
    saved this session, and the tools' `learning_damaged` says so."""
    file = GuardedDictionary(dictionaries / f"{learner_dictionary(english)}.sqlite")
    dictionary: ChineseDictionary | EnglishDictionary = (
        EnglishDictionary(file) if english else ChineseDictionary(file)
    )

    def facts(entry_id: EntryId, scheme: str) -> EntryFacts | None:
        return dictionary.facts(entry_id, scheme)

    scheme = ENGLISH_FREQUENCY if english else DEFAULT_CHINESE_SCHEME
    data.mkdir(parents=True, exist_ok=True)
    path = learning_file(data, english)
    opened: list[SqliteLearningStore] = []

    def open_store() -> SqliteLearningStore:
        opened.append(open_learning_store(path))
        return opened[-1]

    # Learning's saves on a thread of their own: never waited for here
    store = BackgroundLearningStore(open_store)
    vocabulary = Vocabulary(store, facts, scheme.id)
    if store.out:  # its first read found damage SQLite's check missed: set
        store.close()  # aside as at the start, and a new one (206)
        store = BackgroundLearningStore(open_store)
        vocabulary = Vocabulary(store, facts, scheme.id)
    # after a dictionary update (decision 0007): one query, not one a word met
    vocabulary.follow_merged_entries(dictionary.merged_ids())
    tools = LearningTools(
        vocabulary,
        dictionary,
        deck_writer=GenankiDeckWriter(),
        basic=basic,
        dictionary_problem=lambda: file.problem,
        learning_data_new=opened[-1].created,
        learning_set_aside=next((o.set_aside for o in opened if o.set_aside), None),
    )
    file.on_problem = lambda _: tools.dictionary_out.emit()  # a query failed
    store.on_damaged = tools.learning_damaged.emit  # later: a save failed (206)
    store.on_deleted = tools.learning_deleted.emit  # its files set aside too (213)
    return tools, store


def start_logging(data: Path) -> None:
    """To a rotating file in the data folder - the log the feedback form
    shows and attaches, where an exception is written as its type and
    place only (`ContentFreeLog`) - and, from source, to the console as
    well (installed, the app has none: sys.stderr is None). From source
    too, so a report sent while trying the app carries its log
    (polyglotic-hq project 062)."""
    form = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    folder = data / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    file = logging.handlers.RotatingFileHandler(
        folder / "polyglotic.log",
        maxBytes=LOG_BYTES,
        backupCount=LOG_FILES,
        encoding="utf-8",
    )
    file.setFormatter(ContentFreeLog(form))
    handlers: list[logging.Handler] = [file]
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(form))
        handlers.append(console)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in handlers:
        root.addHandler(handler)
    # The caption log (core.listening.delays; polyglotic-hq 271): a line per
    # caption event, several a second while someone talks - in a file of
    # its own, so it never pushes the app's own lines out of theirs.
    captions = logging.handlers.RotatingFileHandler(
        folder / CAPTION_LOG_FILE,
        maxBytes=CAPTION_LOG_BYTES,
        backupCount=CAPTION_LOG_FILES,
        encoding="utf-8",
    )
    captions.setFormatter(ContentFreeLog("%(asctime)s %(message)s"))
    caption_log = logging.getLogger(CAPTION_LOG)
    caption_log.addHandler(captions)
    caption_log.propagate = False


class ContentFreeLog(logging.Formatter):
    """The log file's lines, with an exception (`log.exception`, ours or a
    library's) as its type and where it was raised, as the crash hook
    writes it - never its traceback, whose file paths hold the user's
    Windows name, nor its message, which may hold a caption, a path or a
    token (polyglotic-hq project 053; 061)."""

    def format(self, record: logging.LogRecord) -> str:
        cached, record.exc_text = record.exc_text, None  # another handler's
        try:
            return super().format(record)
        finally:
            record.exc_text = cached

    def formatException(
        self,
        ei: tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None],
    ) -> str:
        kind, _, tb = ei
        if kind is None:
            return ""
        return f"{type_name(kind)} at {where(tb)}"


def where(tb: TracebackType | None) -> str:
    """Where an exception was raised, as `file.py:line in function` - the
    innermost frame, and the innermost of the app's own when that's
    another. File names only: a full path holds the user's name."""
    frames = traceback.extract_tb(tb)
    if not frames:
        return "an unknown place"

    def place(frame: traceback.FrameSummary) -> str:
        return f"{Path(frame.filename).name}:{frame.lineno} in {frame.name}"

    ours = [f for f in frames if "polyglotic_desktop" in Path(f.filename).parts]
    if ours and ours[-1] is not frames[-1]:
        return f"{place(frames[-1])}, from {place(ours[-1])}"
    return place(frames[-1])


def type_name(kind: type[BaseException]) -> str:
    module = kind.__module__
    return (
        kind.__qualname__ if module == "builtins" else f"{module}.{kind.__qualname__}"
    )


class CrashLog:
    """Exceptions nothing caught, logged by their type and where they were
    raised - never their message, which may hold a caption, a path or a
    token. Installed, the app has no console, so without this a failure at
    start ends it without a trace (polyglotic-hq project 042, Medium 4).

    Before the interface runs (`running` False) such an exception ends the
    app: `show_failure`, when given (installed), tells the user first. While
    it runs, Qt hands an exception from a slot here and carries on, and a
    thread's ends only that thread: both are logged, nothing shown.

    Each is also noted in `marker` (when given) - when, its type and place,
    whether at start, and the listening session then (`session`) - so the
    next start can offer to send a report with the log (project 053)."""

    def __init__(
        self,
        show_failure: Callable[[], None] | None = None,
        marker: Path | None = None,
    ) -> None:
        self.show_failure = show_failure
        self.marker = marker
        self.session: Callable[[], str | None] = lambda: None
        self.running = False

    def install(self) -> None:
        sys.excepthook = self.uncaught
        threading.excepthook = self.uncaught_in_thread

    def uncaught(
        self,
        kind: type[BaseException],
        value: BaseException,
        tb: TracebackType | None,
    ) -> None:
        if issubclass(kind, KeyboardInterrupt):
            return
        stage = "while running" if self.running else "at start"
        log.error("uncaught %s %s, at %s", type_name(kind), stage, where(tb))
        self._note(type_name(kind), where(tb), at_start=not self.running)
        if not self.running and self.show_failure is not None:
            self.show_failure()

    def uncaught_in_thread(self, args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        log.error(
            "uncaught %s on thread %s, at %s",
            type_name(args.exc_type),
            args.thread.name if args.thread is not None else "?",
            where(args.exc_traceback),
        )
        self._note(type_name(args.exc_type), where(args.exc_traceback), False)

    def _note(self, what: str, place: str, at_start: bool) -> None:
        """The latest such error, for the next start (`last_crash`)."""
        if self.marker is None:
            return
        noted = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "what": what,
            "where": place,
            "at_start": at_start,
            "session_id": self.session(),
        }
        try:
            self.marker.parent.mkdir(parents=True, exist_ok=True)
            self.marker.write_text(json.dumps(noted), encoding="utf-8")
        except OSError:
            pass  # the log has it; only the offer is lost


@dataclass(frozen=True)
class LastCrash:
    """An error nothing caught, the last time the app ran."""

    at_start: bool  # it stopped the app starting
    session_id: str | None


def last_crash(marker: Path) -> LastCrash | None:
    """What `CrashLog` noted last time, read once: the note is deleted, so
    Home offers a report for it only once."""
    try:
        noted = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        marker.unlink(missing_ok=True)
    if not isinstance(noted, dict):
        return None
    session = noted.get("session_id")
    return LastCrash(
        bool(noted.get("at_start")), session if isinstance(session, str) else None
    )


def show_start_failure(data: Path, show_error: ErrorBox) -> None:
    """The box an installed app shows when it can't start."""
    show_error(
        "Polyglotic",
        "Polyglotic couldn't start, and has closed.\n\n"
        "What went wrong is in its log, which never holds anything you heard,"
        f" said or saw:\n{data / 'logs' / 'polyglotic.log'}\n\n"
        "Try starting it again. If it still won't start, please send us that file.",
    )


class NoApps:
    """The apps with sound, for the install check: none - it looks at
    nothing on the PC."""

    def playing_apps(self) -> list[PlayingApp]:
        return []


def try_the_windows(interface: Interface, desktop: DesktopApp) -> list[str]:
    """Each of the new interface's windows built and shown once (offscreen,
    for the install check), wired as `main` wires them: a caption window,
    the joined window, a transcript and the lookup card, on two made-up
    sources. Returns the windows built, in that order."""
    app = QApplication.instance()
    windows, transcripts = interface.windows, interface.transcripts
    wire_caption_windows(windows, desktop, lambda: None)
    wire_transcripts(transcripts, desktop)
    first, second = SourceId("check-1"), SourceId("check-2")
    built: list[str] = []
    windows.set_captioned([("check-1", first)])
    transcripts.follow()
    if windows.windows["check-1"].isVisible():
        built.append("caption_window")
    windows.set_captioned([("check-1", first), ("check-2", second)])
    windows.join()
    joined = windows.joined_window
    if joined is not None and joined.isVisible():
        built.append("joined_window")
    windows.separate()
    transcripts.follow()
    transcripts.show("check-1")
    shown = transcripts.shown.get("check-1")
    if shown is not None and shown.isVisible():
        built.append("transcript")
    card = windows.card
    if card is not None:
        area = Rect(0, 0, 1280, 720)
        word = WordAt(
            "你好",
            LookupContext("你好"),
            (0, 2),
            Rect(100, 600, 40, 24),
            Rect(80, 590, 600, 44),
            area,
            (0, 0, 0, 2),
        )
        card.pin(word)
        if card.isVisible():
            built.append("lookup_card")
        card.close_card()
    if app is not None:
        app.processEvents()
    return built


def check_install(
    report: Path,
    dictionaries: Path,
    feed: str | None = None,
    learners: Path | None = None,
) -> int:
    """Everything the app needs, built and tried once - Qt (offscreen, so no
    window appears), both dictionaries and the learner's data (in a
    temporary folder), the interface as `main` builds it (`new_interface`)
    and each of its windows (`try_the_windows`), the speech-detection model
    on a second of silence, the Opus encoder - with nothing shown,
    captured, sent or written outside that folder. Writes what it found to
    `report` as JSON; 0 if all of it worked. The release build runs it on
    the packed app to prove the bundle is whole, and to time a start:
    `window_seconds`, from the check's start (after Python's imports) to
    the main window's first paint, and `launch_seconds`, the same from the
    process's launch (the interpreter and the imports included) - the
    budget is `perf.budgets`' START_FROM_SOURCE from source and
    START_PACKED packed. A dictionary that's missing or can't be read is
    named in `dictionaries_out` with why, and fails the check - after
    everything else is built without it, as the app starts without it
    (polyglotic-hq 199). `learning_set_aside` names the learning data
    files set aside in the learner's data folder (`learners`, else the app's),
    each because it couldn't be read (polyglotic-hq 206) - only listed,
    never opened; the app starts with a new one, so the check passes.
    `learning_unreadable` gives, per learning store there, how many rows
    the start leaves out because they can't be read - counts only, read
    without writing (polyglotic-hq 207); the check passes, as the app
    starts without them, unless a store has too many and the app would
    refuse it (`learning_refused`, the store and its table).

    With `feed` (`--updates`), an installed copy also looks there for an
    update and downloads it - never applies it: CI installs a build on its
    runner and proves the updater reads a feed it packed."""
    started = time.perf_counter()
    found: dict[str, object] = {"frozen": installed()}
    try:
        release = this_release()
        found.update(version=release.version, channel=release.channel)
        existing = QApplication.instance()
        app = (
            existing
            if isinstance(existing, QApplication)
            else QApplication(["polyglotic", "-platform", "offscreen"])
        )
        found["qt"] = qVersion()
        # the learning stores are closed before the folder is removed, even
        # when a step fails (Windows can't delete an open SQLite file);
        # anything still open is left to Windows' temporary-files clean-up
        # rather than failing the check
        with (
            tempfile.TemporaryDirectory(
                prefix="polyglotic-check-", ignore_cleanup_errors=True
            ) as folder,
            contextlib.ExitStack() as closing,
        ):
            data = Path(folder)
            english_tools, english = learner_tools(dictionaries, True, data / "english")
            closing.callback(english.close)
            tools, chinese = learner_tools(dictionaries, False, data / "chinese")
            closing.callback(chinese.close)
            found["dictionaries"] = [
                file.name for file in sorted(dictionaries.glob("*.sqlite"))
            ]
            out = {
                f"{learner_dictionary(english_learner)}.sqlite": problem.value
                for english_learner, each in ((False, tools), (True, english_tools))
                if (problem := each.dictionary_problem) is not None
            }
            found["dictionaries_out"] = out
            store = JsonSettingsStore(data / "settings.json")
            desktop = DesktopApp(store, tools, NoApps())
            closing.callback(desktop.close)
            interface = new_interface(desktop, store, tools, per_app=True)
            closing.callback(interface.close)
            interface.hub.window.show()  # offscreen: a first paint, seen by no one
            app.processEvents()
            found["window_seconds"] = round(time.perf_counter() - started, 3)
            found["launch_seconds"] = round(os_adapters().seconds_since_launch(), 3)
            # the Microsoft Store's package it runs from, if any (decision 0056)
            found["store_package"] = os_adapters().store_package()
            learner_data = learners or os_adapters().data_folder()
            found["learning_set_aside"] = set_aside_in(learner_data)
            unreadable = unreadable_in(learner_data)
            found["learning_unreadable"] = {
                name: rows for name, (rows, _) in unreadable.items()
            }
            refused = {name: table for name, (_, table) in unreadable.items() if table}
            found["learning_refused"] = refused
            # imported after the window, as main() has it
            import numpy as np

            from polyglotic_desktop.adapters.signed_feed import (
                FeedNotTrusted,
                public_keys,
                verify,
            )
            from polyglotic_desktop.platform.opus import encode_ogg_opus
            from polyglotic_desktop.platform.speech_detection import (
                SpeechDetector,
                load_model,
            )

            silence = np.zeros(16_000, dtype=np.float32)
            frames = SpeechDetector(load_model()).feed(0.0, silence)
            found["speech_frames"] = sum(frame.speech for frame in frames)
            found["opus_bytes"] = len(encode_ogg_opus(silence))
            found["ready_seconds"] = round(time.perf_counter() - started, 3)
            found["windows"] = try_the_windows(interface, desktop)
            key, signature = RFC8032_TEST_1  # the signed feed's check works here
            verify(b"", signature, public_keys([key]))
            try:
                verify(b"x", signature, public_keys([key]))
            except FeedNotTrusted:
                found["feed_signature_check"] = True
            installer = updater(feed or UPDATES)
            found["installed"] = installer.installed()
            if feed is not None and found["installed"]:
                update = installer.find(None, False)
                found["update_found"] = update.version if update else None
                if update is not None:
                    installer.download(update)
                    found["update_downloaded"] = True
        found["ok"] = not out and not refused
        if out:
            found["error"] = "dictionaries out: " + ", ".join(sorted(out))
        elif refused:
            found["error"] = "learning data refused: " + ", ".join(sorted(refused))
    except Exception as e:  # noqa: BLE001 - reported: a windowless app has no console
        found.update(ok=False, error=f"{type(e).__name__}: {e}")
    report.write_text(json.dumps(found, indent=2), encoding="utf-8")
    return 0 if found["ok"] else 1


def import_the_rest() -> None:
    """The libraries the window doesn't need - pydantic, websockets, numpy,
    onnxruntime - imported on a thread of their own at start: about 0.3 s
    that would otherwise hold the interface thread right after the first
    paint (136). Each module is imported once whichever thread asks first."""
    import polyglotic_desktop.connection.client
    import polyglotic_desktop.connection.exchange
    import polyglotic_desktop.connection.feedback
    import polyglotic_desktop.connection.milestones
    import polyglotic_desktop.connection.sign_in
    import polyglotic_desktop.platform.speech_detection
    import polyglotic_desktop.platform.speech_pipeline  # noqa: F401


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """The command line's options."""
    parser = argparse.ArgumentParser(prog="python -m polyglotic_desktop.main")
    parser.add_argument(
        "--server",
        default=SERVER,
        help=f"the server (default {SERVER}); e.g. http://127.0.0.1:8217",
    )
    parser.add_argument("--dictionaries", type=Path, default=dictionaries_folder())
    parser.add_argument(
        "--data", type=Path, default=None, help="where settings and learning data live"
    )
    parser.add_argument(
        "--credentials",
        default=None,
        help="the Credential Manager entry (default: the app's for its own server;"
        " Polyglotic/device@HOST:PORT for any other --server)",
    )
    parser.add_argument(
        "--updates",
        default=UPDATES,
        help=f"the update feed (default {UPDATES}), or a folder on this PC",
    )
    # the developer switch (decision 0031), now the default: accepted and
    # ignored until the first release after it (decision 0032)
    parser.add_argument("--next-interface", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        IN_TRAY,
        action="store_true",
        help="start in the tray, without the main window (as Windows starts it)",
    )
    parser.add_argument(
        "--basic-dictionaries",
        nargs="?",
        const="en",
        choices=["en", "zh"],
        default=None,
        help="developers, from source: look up words in Japanese and Spanish"
        " captions in the basic dictionary packs (tools.dictionaries.packs),"
        " with English or Chinese meanings - nothing is kept or sent",
    )
    parser.add_argument(
        "--check-install",
        type=Path,
        metavar="REPORT",
        help="build everything without showing, capturing or connecting;"
        " write what was found to REPORT (JSON) and quit",
    )
    return parser.parse_args(argv)


def store_copy_here() -> str | None:
    """The Microsoft Store's package this copy runs from, if it does
    (decision 0056) - asked before anything else, Velopack's start-up
    included. None too where this OS has no adapters yet, so that
    `--check-install` still runs and reports what's missing."""
    try:
        return os_adapters().store_package()  # imports only
    except NoOsAdapters:
        return None


def windows_deleted() -> None:
    """Every window deleted now, once the event loop has ended - the main
    window with its pages and their panels, the caption windows, the
    transcripts, the lookup card - while Qt and Python are both still up.
    Left to Python's exit, they are torn down in no set order while panels
    are still bound to their views: the crash 261's tests hit at exit (code
    134 on Linux). The windows Quit closed are deleted first (their
    `deleteLater`), then each window left, one at a time, asking Qt again
    after each: deleting one deletes the windows it owns."""
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    for _ in range(1000):  # a bound, never reached: each pass deletes one
        alive = QApplication.topLevelWidgets()
        if not alive:
            break
        shiboken6.delete(alive[0])
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def main(argv: list[str] | None = None) -> None:
    store_copy = store_copy_here()  # whose copy this is comes first
    if store_copy is None:  # the Store's copy has no Velopack (decision 0056)
        run_installer_hooks()  # first: the installer's hooks exit here (Velopack)
    args = arguments(argv)
    if args.check_install:
        feed = args.updates if args.updates != UPDATES else None
        sys.exit(check_install(args.check_install, args.dictionaries, feed, args.data))
    system = os_adapters()
    taskbar_id = system.taskbar_identity(TASKBAR_ID)  # before any window
    data = args.data or system.data_folder()
    start_logging(data)
    crashes = CrashLog(
        partial(show_start_failure, data, system.show_error) if installed() else None,
        data / CRASH_NOTE,
    )
    crashed = last_crash(data / CRASH_NOTE)  # before this run can note one
    crashes.install()
    release = this_release()
    log.info(
        "Polyglotic %s (%s), taskbar ID %s%s",
        release.version,
        release.channel,
        taskbar_id,
        ", the Microsoft Store's package" if store_copy else "",
    )
    # the Store's copy: the Store updates it, nothing here (decision 0056)
    updater_or_store = None if store_copy else updater(args.updates)
    updates = BackgroundUpdates(Updates(updater_or_store, release.channel))
    updates.check()  # before anything else is built: a broken start can still update

    # the connection's and speech libraries load on a thread while the window
    # is built, so neither the window nor the interface thread waits on them
    # (they're imported where used, after the first paint - 136)
    threading.Thread(target=import_the_rest, name="imports", daemon=True).start()
    app = QApplication(sys.argv[:1])
    # Windows' Text size, from the system font Qt read (135's proposal A)
    style.use_text_scale(style.text_scale_of(app.font()))
    app.setApplicationName("Polyglotic")
    # every window's: its title bar, the taskbar's button and Alt-Tab - else
    # Windows' plain application icon, which Qt's window classes carry
    # (polyglotic-hq 245)
    app.setWindowIcon(icons.app_icon())
    app.setQuitOnLastWindowClosed(False)  # the tray keeps it running
    watchdog = Watchdog(parent=app)  # logs a stretch over 50 ms: names, durations
    watchdog.start()
    store = JsonSettingsStore(data / "settings.json")
    start_interface_language(app, store)  # its translators are the app's children
    # the app's own text size (Settings > App), on Windows': every window from
    # the first run's on is built at it (polyglotic-hq 292, decision 0084)
    style.use_app_text_size(Settings(store).value.app_text_size)
    basic = (
        basic_dictionaries(
            packs_folder(args.dictionaries, data), args.basic_dictionaries
        )
        if args.basic_dictionaries
        else None
    )
    # an unreadable one is set aside; written on a thread of its own, in
    # order - the consent choice and every event (polyglotic-hq 136, 144)
    outbox = BackgroundOutbox(lambda: open_outbox(data / "outbox.sqlite"))
    credentials = system.credentials(credentials_entry(args.server, args.credentials))
    app_info = AppInfo.this_app(system.os_name(), system.os_version())
    # the cohort each code signs in with: applied once the dialog closes -
    # the first run's once the rest is built (polyglotic-hq 279)
    signed_in_cohort = SignedInCohort()

    def redeem_code(typed: str, signed_in: bool = False) -> SignInFailed | None:
        # the connection's, imported here: the first run's code comes before
        # the rest is imported (after the window's first paint)
        from polyglotic_desktop.connection.sign_in import redeem

        try:
            return signed_in_cohort.answered(
                redeem(args.server, typed, credentials, app_info, signed_in=signed_in)
            )
        except ValueError:  # the server's address isn't one the token may go to
            return SignInFailed(SignInProblem.UNREACHABLE)

    # the first run's screens, or new words of the tester agreement: the
    # level, what's shared and the yes (kept once the exchange exists), the
    # code - each after the first with Back (polyglotic-hq 250); no language
    # (293): the tools are the language learned's, or a guess from Windows'
    try:
        started = first_run(
            store,
            lambda english: learner_tools(args.dictionaries, english, data, basic),
            outbox.consent(),
            redeem_code if credentials.load() is None else None,
            code_again=credentials.install_id() is not None,
            windows_languages=interface_language.windows_languages(),
            kept=lambda code: learning_file(data, code == "en").exists(),
        )
    except NotAgreed:  # closed without the yes: no further (polyglotic-hq 185)
        log.info("the tester agreement wasn't accepted: quitting")
        outbox.close()
        store.close()
        watchdog.stop()
        return
    tools, learning_store, first = started.tools, started.learning_store, started.first
    english = not tools.is_chinese
    tools.prepare()  # the word split's data, off this thread (0.2 s): a caption
    # before it's read shows at once, counted and marked when it is (136);
    # then what Words reads for every word met (polyglotic-hq 212)
    desktop = DesktopApp(
        store,
        tools,
        system.app_list(),
        your_sources=(MIC,),
        light_taskbar=system.light_taskbar,
    )
    # apps one by one: promised, tried (Windows 10 2004 to 22H2), or not
    # (decision 0076) - the log's line says which, and how it went
    per_app = AppsOneByOne(
        system.app_capture_support(),
        desktop.settings,
        system.windows_build(),
        app_info.app_version,
        system.app_capture_trial,
        desktop,
    )
    interface = new_interface(
        desktop,
        store,
        tools,
        per_app.on,
        system.keys,
        system.on_top(),
        system.common_apps,
    )
    windows, transcripts, hub = interface.windows, interface.transcripts, interface.hub
    if per_app.fell_back:  # here before: Home offers "Try apps again" (0076)
        hub.fell_back = True
        hub.follow()
    over: QWidget = hub.window  # what today's dialogs open over
    hub.level_of = partial(kept_level, data)  # another language's, on Learning
    hub.show_learning()

    def chosen() -> ListeningSettings:
        """The listening settings now - each window's languages its source's."""
        return listening_settings(
            desktop.settings.value, windows.targets(), windows.spoken_languages()
        )

    # the window first; then the rest - speech detection, the connection
    desktop.show_tray()
    hub.window.keep_in_tray = desktop.tray is not None  # closing it hides it
    hub.window.follows_text_size = True  # a change Qt reports restyles it
    if notice := start_notice(store.set_aside, windows.taken_off):
        desktop.home_notice.emit(notice)
    # the installed app can start with Windows (176) - not the Store's copy
    # yet: its Run value would be the package's private copy (decision 0056)
    if installed() and store_copy is None:
        hub.startup = system.start_at_sign_in(sys.executable)
    if not (args.in_tray and desktop.tray is not None):
        desktop.show_window()  # started by Windows: in the tray (176)
    app.processEvents()  # its first paint
    if desktop.apps is not None:  # the apps with sound: first looked for now (291)
        desktop.apps.look()

    # imported only now - pydantic, websockets, numpy and onnxruntime take
    # about 0.3 s - so the window is up first (108's fix f, project 136)
    from polyglotic_desktop.connection import listening
    from polyglotic_desktop.connection.client import Connection
    from polyglotic_desktop.connection.exchange import DataExchange
    from polyglotic_desktop.connection.feedback import RETRY_EVERY_SEC, FeedbackSender
    from polyglotic_desktop.connection.milestones import Milestones
    from polyglotic_desktop.connection.problem_reports import ProblemReportSender
    from polyglotic_desktop.platform.speech_detection import SpeechDetector, load_model
    from polyglotic_desktop.platform.speech_pipeline import SpeechPipeline

    exchanged = QtExchange(tools, desktop)
    # an account learning both languages: only this one's entries come in
    exchange = DataExchange(
        outbox,
        outbox,
        exchanged,
        learner_dictionary(english),
        whole_state=tools.vocabulary.learning_state,  # after a restore (166)
    )
    # words saved elsewhere while the dictionary is out arrive once it's whole
    if tools.dictionary_problem is None:
        exchange.dictionary_whole()
    else:
        exchange.dictionary_out()
    tools.dictionary_out.connect(exchange.dictionary_out)  # from any thread: locked
    if tools.learning_data_new:  # new, or set aside: what the server keeps comes back
        exchange.learning_data_new()  # (polyglotic-hq 206)

    def to_server(event: LearningEvent | VocabularyChanged) -> None:
        if not isinstance(event, VocabularyChanged):
            exchange.learning(event)

    tools.vocabulary.subscribe(to_server)

    value = desktop.settings.value
    connection: Connection | None = None

    def speech_ready() -> None:
        session = connection.listening if connection is not None else None
        if session is not None:
            session.speech_ready()

    timing = CaptionTiming(
        value.live_interval,
        rules=value.caption_mode.rules,
        max_wait=value.max_wait_for_text,
    )
    # the speech-detection model (onnxruntime; 0.1-0.2 s) loads on a thread
    # of its own; each source's detector is made from it on that source's
    # capture thread, at its first audio - never here (polyglotic-hq 136)
    loader = ThreadPoolExecutor(1, thread_name_prefix="speech-model")
    model = loader.submit(load_model)
    loader.shutdown(wait=False)
    pipeline = SpeechPipeline(
        lambda: SpeechDetector(model.result()),
        timing,
        on_ready=speech_ready,
        outputs_playing=system.outputs_playing,
    )
    # the install's milestones (usage statistics, with consent): a PC that
    # has never connected is a new install (polyglotic-hq project 134)
    milestones = Milestones(outbox, exchange, app_info)
    # the outbox's reads here first (the exchange's and the milestones'
    # notes): a read waits for the writes queued before it, and the
    # consent choice's are the first (polyglotic-hq project 144)
    if first is not None:
        exchange.choose_consent(*first.choices, agreement=first.agreement)
    # noted in the outbox and sent if due, once a read says whether this PC
    # has connected (it waits for the consent choice's writes): off this
    # thread, as everything else of its is (polyglotic-hq project 136)
    threading.Thread(
        target=lambda: milestones.started(fresh=not exchange.has_connected()),
        name="milestones",
        daemon=True,
    ).start()
    listener = QtListener(desktop, pipeline, updates, hub.account)
    listener.plan_shown.connect(hub.show_plan)
    # a busy time, said where the learner looks
    listener.busy_changed.connect(windows.set_busy)
    listener.spoken_per_source.connect(windows.set_spoken_per_source)
    listener.busy_changed.connect(hub.set_busy)
    listener.update_found.connect(hub.set_update_found)
    connection = Connection(
        args.server, credentials, app_info, exchange, listener, milestones=milestones
    )
    account = hub.account
    reports = FeedbackFolder(data / "feedback")
    feedback = QtFeedback(desktop)
    sender = FeedbackSender(args.server, credentials, reports, feedback.outcome)

    problem_reports = ProblemReportFolder(data / "problem-reports")
    problem_sender = ProblemReportSender(
        args.server, credentials, problem_reports, feedback.outcome_of
    )

    crashes.session = lambda: listener.session_id

    def cohort_seen(cohort: str | None) -> None:
        """The account's test group, from a session's `welcome` or the
        redeem answer of a code just signed in with (`cohort_known`)."""
        if cohort is not None:
            cohort_known(cohort, desktop.settings, exchange, windows.set_reporting)

    listener.cohort_seen.connect(cohort_seen)
    # the caption windows' strips too (a tester's, as last known)
    windows.set_reporting(is_tester(desktop.settings.value))
    cohort_seen(signed_in_cohort.take())  # the first run's code, if it signed in
    windows.report_wanted.connect(lambda: open_feedback("problem"))
    report_window = OneReportWindow()

    def open_problem_report(
        session_id: str | None, check_result: str | None = None
    ) -> None:
        """An alpha tester's "Report a problem": the dialog over the window,
        not modal; what's left ticked is kept and sent off this thread. One
        at a time: asked again, the open one comes to the front (278)."""
        from polyglotic_desktop.connection import protocol

        if report_window.front():
            return
        captions = captions_as_shown(desktop.feed.history.captions, datetime.now(UTC))
        speech = speech_by_source(pipeline.held_speech())
        names = {str(sid): title for sid, (_, title) in sources.shown().items()}
        for part in speech:
            if desktop.feed.history.is_yours(part.source_id):
                names[str(part.source_id)] = mic_name()
        log_text = read_log(data / "logs")
        values = desktop.settings.value.to_stored()
        facts = report_facts(app_info, release.channel, speech, per_app.line)
        dialog = ProblemReportDialog(
            problem_report_parts(
                log_text, values, facts, captions, speech, names, check_result
            ),
            feedback_versions(app_info),
            over,
        )

        def send() -> None:
            text, ticked = dialog.chosen()
            if check_result and "check" in ticked:
                text = f"{text}\n\n--- no-captions check ---\n{check_result}".strip()
            report = ProblemReport(
                id=str(uuid.uuid4()),
                at=protocol.at(datetime.now(UTC)),
                text=text[:5000],
                app_version=app_info.app_version,
                os=app_info.os,
                os_version=app_info.os_version,
                session_id=session_id,
                log=log_text if "log" in ticked else None,
                settings=values if "settings" in ticked else None,
                facts=facts if "facts" in ticked else None,
                captions=captions if "captions" in ticked else None,
                speech=tuple(
                    ReportedSpeech(
                        str(clip.caption_id),
                        str(clip.source_id),
                        clip.category.value,
                        clip.start,
                        clip.end,
                        clip.audio,
                    )
                    for part in speech
                    if f"speech:{part.source_id}" in ticked
                    for clip in part.clips
                ),
            )
            feedback.just_sent = report.id
            if credentials.load() is None:
                desktop.show_feedback("sign_in", True)
            problem_sender.keep_and_send(report)

        dialog.sent.connect(send)
        report_window.opened(dialog)
        dialog.show()
        dialog.raise_()

    def open_feedback(
        kind: str, session_id: str | None = None, check_result: str | None = None
    ) -> None:
        if kind == "problem" and is_tester(desktop.settings.value):
            open_problem_report(session_id or listener.session_id, check_result)
            return
        report = ask_for_feedback(
            cast(ReportKind, kind),
            data / "logs",
            app_info,
            session_id or listener.session_id,
            reports,
            over,
            check_result,
        )
        if report is None:
            return
        feedback.just_sent = report.id
        if credentials.load() is None:
            desktop.show_feedback("sign_in", True)
        sender.send_waiting()

    desktop.feedback_wanted.connect(open_feedback)
    desktop.check_report_wanted.connect(
        lambda result: open_feedback("problem", check_result=result)
    )
    desktop.set_activity(pipeline.activity)
    settings_page = hub.settings
    settings_page.check_for_updates.connect(updates.check)

    def restart_into_update() -> None:
        """Restart now (polyglotic-hq 299): the app quits as Quit does -
        everything saved - and the installer applies the update and starts
        the new version."""
        log.info("restart now: the update applies as the app quits")
        updates.restart_when_quitting()
        desktop.quit.trigger()

    update_shown = UpdateShown(
        hub.home,
        desktop,
        None if store_copy is not None else settings_page,
        restart_into_update,
    )
    updates.tell(update_shown.found)
    settings_page.set_notices(third_party_notices())

    if crashed is not None:  # offered once, quietly, on Home
        hub.home.offer_crash_report(crashed.at_start)
        hub.home.crash_report_wanted.connect(
            lambda: open_feedback("problem", crashed.session_id)
        )
    settings_page.set_version(
        release.version, release.channel, store=store_copy is not None
    )

    def counted(event: LearningEvent | VocabularyChanged) -> None:
        if not isinstance(event, VocabularyChanged):
            connection.learned(event)  # lookups and saves, in the session's summary

    tools.vocabulary.subscribe(counted)
    # the listening settings reach the session once a change settles (273)
    handoff = SettingsHandoff(lambda: connection.listening, chosen, desktop)

    # dictation's pieces (polyglotic-hq 283, decision 0073) wait here and go
    # out on the listening session before the captions' speech: the learner
    # is waiting for them
    from polyglotic_desktop.core.listening.pending import PendingSpeech

    dictation_waiting: PendingSpeech[bytes | None] = PendingSpeech()
    dictation_lock = threading.Lock()

    def dictation_send(request: TranscriptionRequest, speech: bytes) -> None:
        with dictation_lock:
            dictation_waiting.put(request, speech)
        speech_ready()

    def dictation_forget() -> None:
        """Dictation gave its pieces up: none still waiting is sent
        (polyglotic-hq 299)."""
        with dictation_lock:
            dictation_waiting.clear()

    def speech_to_send() -> tuple[Decision, bytes | None] | None:
        """What the listening session sends next: a dictation's piece first,
        then the captions' speech (the pipeline's)."""
        with dictation_lock:
            ready = dictation_waiting.take()
        return ready if ready is not None else pipeline.take()

    def listen() -> None:
        current, settings = desktop.settings.value, chosen()
        session = connection.start_listening(
            settings,
            speech_to_send,
            current.live_interval,
            current.caption_mode,
        )
        handoff.started(session, settings)

    def not_listening() -> None:
        """Home's state while nothing is chosen to caption (no session)."""
        signed_in = credentials.load() is not None
        desktop.set_connection(
            ConnectionState.NOT_CONNECTED
            if signed_in
            else ConnectionState.SIGN_IN_NEEDED
        )

    def sign_in() -> None:
        again = credentials.install_id() is not None  # signed in here before (288)
        if SignInDialog(redeem_code, over, again=again).exec():
            account.set_signed_in(True)
            cohort_seen(signed_in_cohort.take())  # before the reports go
            sender.send_waiting()  # reports kept until now
            problem_sender.send_waiting()
            connection.stop_listening()  # the one that stopped for want of a token
            if not listen_then_sync(connection, listen, desktop.settings.value):
                not_listening()

    def listen_here() -> None:
        """Home's "Listen here" after listening moved to another device: the
        stopped session goes, and a new one takes listening back (the other
        device is then the one told)."""
        connection.stop_listening()
        if not listen_then_sync(connection, listen, desktop.settings.value):
            not_listening()

    hub.home.listen_here_wanted.connect(listen_here)

    def have_code() -> None:
        """Account's "I have a code", signed in: the code from a Plus email,
        onto this account (polyglotic-hq 185); then a new session, whose
        `welcome.plan` says the Plus it brought."""
        if SignInDialog(partial(redeem_code, signed_in=True), over).exec():
            cohort_seen(signed_in_cohort.take())  # the account's, as it was
            listen_here()

    account.have_code.triggered.connect(have_code)

    def plus_again(line: PlanLine) -> None:
        if plus_is_back(desktop.connection, line):
            listen_here()

    listener.plan_shown.connect(plus_again)

    def sign_out() -> None:
        if confirm_sign_out(over, unsent=exchange.has_waiting()):
            account.set_signed_in(False)
            dropped = reports.clear()  # nothing from this account reaches the next
            dropped += problem_reports.clear()
            desktop.settings.update(cohort=None)  # the next account says its own
            windows.set_reporting(False)
            if dropped:
                log.info("signed out: %d waiting report(s) dropped", dropped)
            desktop.set_connection(ConnectionState.SIGN_IN_NEEDED)
            threading.Thread(target=connection.sign_out, daemon=True).start()

    def choose_what_to_share() -> None:
        dialog = ConsentDialog(
            exchange.consent, over, tester=is_tester(desktop.settings.value)
        )
        if dialog.exec():  # the yes given at start goes with it
            exchange.choose_consent(*dialog.choices(), agreement=dialog.agreement())

    def send_recheck(
        caption: Caption,
    ) -> tuple[SourceCategory | None, RecheckOutcome | None]:
        """A flagged line's held speech to the server ("Looks wrong?"), with
        the listening settings as they are now - in its source's languages."""
        held = pipeline.get(caption.caption_id)
        if held is None:
            return None, RecheckOutcome.NOT_HELD
        now = chosen()
        request = RecheckRequest(
            caption_id=caption.caption_id,
            source=Source(held.source_id, held.category),
            speech_start=held.start,
            speech_end=held.end,
            audio=held.audio,
            spoken_language=now.spoken_language_of(held.source_id),
            targets=now.targets_of(held.source_id),
            second_languages=now.second_languages,
        )
        sent = connection.recheck(request)
        return held.category, None if sent else RecheckOutcome.NOT_LISTENING

    def count_flag(flagged: LineFlagged) -> None:
        exchange.usage(  # kept only with consent to usage statistics
            listening.LINE_FLAGGED, listening.line_flagged(flagged), datetime.now(UTC)
        )
        connection.did(SessionAction.LINE_FLAGGED)  # and in the session's summary

    desktop.looks_wrong.send = send_recheck
    desktop.looks_wrong.count = count_flag

    def delete_learning() -> None:
        dialog = DeleteLearningDialog(over, learning_store.set_aside_copies())
        if dialog.exec():
            pipeline.forget_recent()
            problem_reports.clear()  # a waiting report's captions and audio too
            exchanged.delete_here = dialog.delete_on_this_pc()
            exchange.delete_learning()

    account.sign_in.triggered.connect(sign_in)
    account.sign_out.triggered.connect(sign_out)
    account.your_data.triggered.connect(choose_what_to_share)
    account.delete_learning.triggered.connect(delete_learning)
    signed_in = credentials.load() is not None
    account.set_signed_in(signed_in)
    if signed_in and exchange.account is not None:  # before any session (223)
        account.show_account(exchange.account)
    apps = desktop.apps
    assert apps is not None  # main always gives DesktopApp the app list
    aloud = system.sound_out()
    # a looked-up word said aloud in one of the PC's voices - and left out of
    # the captions: the sources that hear it are hushed while it plays
    # (polyglotic-hq 286, decision 0077). Nothing is sent anywhere.
    speaker = system.speaker()
    if windows.card is not None:
        windows.card.use_speech(WordSpeech(speaker, hush=pipeline.hush, parent=desktop))
    # Windows' voices listed once the app has started, never in its way
    QTimer.singleShot(VOICES_AFTER_START_MS, speaker.look_for_voices)

    def sample_capture() -> SampleCapture | None:
        """The sample in the language learned, played aloud as it starts."""
        found = sample_file(sample_language(desktop.settings.value, desktop.tools))
        if found is None:
            return None

        def play(audio: Audio, rate: int) -> Callable[[], None]:
            aloud.play(audio, rate)
            return aloud.stop

        return SampleCapture(found, play)

    sources = Sources(
        pipeline,
        apps,
        per_app.on,
        # each tells the trial, if apps one by one is being tried (0076)
        lambda process_id, name: system.app_capture(process_id, name, per_app.trial),
        system.system_capture,
        system.mic_capture,
        desktop.set_app_sources,
        connection.captured,  # per app vs whole system, in the session's summary
        signed_in,  # nothing captured while signed out
        everything_else_capture=lambda left_out: system.everything_else_capture(
            left_out, per_app.trial
        ),
        sample_capture=sample_capture,
    )

    def signed_in_or_out(state: ConnectionState, _retry_in: object) -> None:
        shown = sources.sample_shown
        sources.set_signed_in(state is not ConnectionState.SIGN_IN_NEEDED)
        if shown and not sources.sample_shown:  # signed out: the sample went (223)
            hub.sample_on = hub.sample_ended = False
            follow_settings(windows, desktop, sources)
            hub.follow()

    desktop.connection_changed.connect(signed_in_or_out)

    # dictation (polyglotic-hq 283, decision 0073): off until turned on;
    # then its key, held, opens the mic, and what was said is typed (imported
    # only now, after the window's first paint, like the connection)
    from polyglotic_desktop.core.listening.dictation import DICTATION_LANGUAGES
    from polyglotic_desktop.platform.dictation_mic import DictationMic
    from polyglotic_desktop.ui.dictation import Dictating
    from polyglotic_desktop.ui_next.dictation_key import key_words
    from polyglotic_desktop.ui_next.dictation_sign import DictationSign
    from polyglotic_desktop.ui_next.languages import dictation_choices

    def dictation_session(wanted: bool) -> bool:
        """Dictation needs a listening session (`wanted`) - one opens if
        none is; False when signed out - or no longer does: it closes if
        nothing else needs it."""
        if wanted and credentials.load() is None:
            return False
        value = desktop.settings.value
        follow_choice(connection, value, listen, desktop, sources.sample_on, wanted)
        return True

    def dictation_has_mic(held: bool, tail: float) -> None:
        """While dictation has the mic, the mic's captions hear silence: what's
        dictated is never also a "You" line (polyglotic-hq 299)."""
        now = time.perf_counter()  # the captures' clock
        if held:
            pipeline.dictation_holds(now)
        else:
            pipeline.dictation_lets_go(now + tail)

    dictation_mic = DictationMic(system.mic_capture)
    dictating = Dictating(
        desktop.settings,
        dictation_mic,
        dictation_send,
        system.type_text,
        system.keyboard_window,
        system.keys,
        dictation_session,
        parent=desktop,
        mic_held=dictation_has_mic,
        forget_unsent=dictation_forget,
    )
    # a session that can't be answered says so at once, not after 10 s (299)
    desktop.connection_changed.connect(
        lambda state, _retry_in: dictating.connection_changed(state)
    )
    dictating.connection_changed(desktop.connection)
    listener.dictated = dictating.answered
    dictation_sign = DictationSign()
    dictating.sign_changed.connect(dictation_sign.show_state)
    dictation_key = DictationKeyHeld(
        lambda key: system.hold_key(
            key, dictating.key_down, dictating.key_up, dictating.key_other
        )
    )
    dictation_was_on = desktop.settings.value.dictation

    def follow_dictation() -> None:
        """Dictation's key taken (or let go) as the settings say - let go
        while Settings' key box listens - and shown in words where it's
        named: Settings, the tray, the sign, Help (polyglotic-hq 289)."""
        nonlocal dictation_was_on
        value = desktop.settings.value
        changed = dictation_key.follow(value.dictation, value.dictation_key)
        if changed and not value.dictation:
            dictating.stop()
        words = key_words(value.dictation_key)
        desktop.show_dictation_key(words)
        hub.help.show_dictation_key(words)
        dictation_sign.key = words
        if value.dictation and not dictation_was_on:
            dictation_sign.show_hint()  # which key to hold, as it's turned on
        dictation_was_on = value.dictation
        settings_page.show_dictation(
            value.dictation,
            value.dictation_key,
            value.dictation_language,
            value.dictation_australian,
            dictation_key.taken,
        )

    def dictation_key_box(listening: bool) -> None:
        dictation_key.box_listening = listening
        follow_dictation()

    def dictation_key_wanted(wanted: str) -> None:
        """A key pressed in Settings: kept if another program doesn't have
        it - else the one before is, and Settings says so."""
        if dictation_key.try_key(wanted, desktop.settings.value.dictation):
            desktop.settings.update(dictation_key=wanted)
        else:
            settings_page.dictation_key_not_taken(wanted)
            follow_dictation()  # the key before, again

    settings_page.dictation_changes.connect(
        lambda changes: desktop.settings.update(**changes)
    )
    settings_page.dictation_key_listening.connect(dictation_key_box)
    settings_page.dictation_key_wanted.connect(dictation_key_wanted)
    # its language as modes at the tray: Detect, English, Mandarin, Cantonese
    desktop.set_dictation_languages(dictation_choices(DICTATION_LANGUAGES))
    desktop.dictation_settings_wanted.connect(hub.open_app_settings)
    follow_dictation()

    def listened(update: CaptionUpdate) -> None:
        """Listening time, from finished captions of what the PC played in
        the language being learned (polyglotic-hq projects 163, 174) - by
        the source's category, never its name; on this PC only."""
        if (
            update.kind is CaptionKind.FINISHED
            and tools.learns(update.language)
            and not desktop.feed.history.is_yours(update.source_id)
        ):
            category = sources.category_of_source(update.source_id)
            if category is not SourceCategory.MIC:
                tools.vocabulary.listened(category.value)

    desktop.feed.applied.connect(listened)

    send_settings = handoff.changed

    chosen_sources = [chosen_capture(desktop.settings.value)]

    def sources_chosen(changed: AppSettings) -> None:
        """`source_selected` when the learner changed what to caption (with
        consent): the mode, how many apps, the mic, and an added app's
        category - never its name."""
        now, picked = chosen_capture(changed), list(changed.apps[:LIMIT])
        if now == chosen_sources[0] and set(picked) == set(before_apps[0]):
            return
        added = next((a for a in picked if a not in before_apps[0]), None)
        before_apps[0] = picked
        chosen_sources[0] = now
        category = sources.category_of(added) if added else None
        exchange.usage(
            listening.SOURCE_SELECTED,
            listening.source_selected(now, category),
            datetime.now(UTC),
        )

    before_apps = [list(desktop.settings.value.apps[:LIMIT])]

    def settings_changed() -> None:
        changed = desktop.settings.value
        follow_settings(windows, desktop, sources)
        follow_transcripts(transcripts)
        send_settings()
        pipeline.set_timing(
            changed.caption_mode.rules,
            changed.live_interval,
            changed.max_wait_for_text,
        )
        sources.follow(captured(changed))  # an app chosen ends the sample
        hub.sample_on, hub.sample_ended = sources.sample_on, sources.sample_kept
        sources_chosen(changed)  # after: an app just added has its category
        follow_dictation()
        follow_choice(
            connection,
            changed,
            listen,
            desktop,
            sources.sample_on,
            dictating.session_wanted,
        )

    def try_sample(on: bool) -> None:
        """Home's sample on or off (polyglotic-hq 176): its source, its
        caption window, and listening while it's on."""
        sources.play_sample(on)
        hub.sample_on, hub.sample_ended = sources.sample_on, False
        follow_settings(windows, desktop, sources)
        send_settings()  # its window's languages
        value = desktop.settings.value
        follow_choice(
            connection,
            value,
            listen,
            desktop,
            sources.sample_on,
            dictating.session_wanted,
        )
        hub.follow()

    hub.sample = try_sample

    def sample_ended() -> None:
        """The sample played to its end (polyglotic-hq 208, 203's option B):
        its window stays for lookups, listening stops once its last caption
        is in (the session sends what waits, then closes), and Home offers
        it again with the next step - an app of the learner's own."""
        sources.end_sample()
        hub.sample_on, hub.sample_ended = False, sources.sample_kept
        follow_settings(windows, desktop, sources)
        value = desktop.settings.value
        follow_choice(
            connection, value, listen, desktop, False, dictating.session_wanted
        )
        hub.follow()

    def sample_window_closed(key: str) -> None:
        if key == SOURCE_KEY_SAMPLE and sources.sample_shown:  # its x: it goes
            try_sample(False)

    windows.stop_wanted.connect(sample_window_closed)

    def apps_changed() -> None:
        """Capturing apps one by one failed here (everything the PC plays
        from now - said once, on Home and the caption windows), or is tried
        again (decision 0076)."""
        sources.per_app = hub.per_app = per_app.on
        hub.fell_back = per_app.fell_back
        settings_changed()  # the sources and windows, now
        hub.follow()
        if per_app.fell_back:
            desktop.home_notice.emit(fell_back_text())
            desktop.caption_notice.emit(fell_back_text())

    per_app.changed.connect(apps_changed)
    hub.apps_again = per_app.try_again

    wire_caption_windows(windows, desktop, send_settings)
    follow_settings(windows, desktop, sources)
    # the mic is captured only while a window shows my speech
    desktop.caption_mic.setChecked(windows.show_mic_anywhere)
    wire_transcripts(transcripts, desktop)
    # what the learner does, in the listening session's summary (project 134)
    transcripts.opened.connect(lambda: connection.did(SessionAction.TRANSCRIPT_OPENED))
    windows.joined_changed.connect(connection.joined)
    connection.joined(windows.joined_window is not None)
    desktop.settings.changed.connect(settings_changed)
    desktop.pause.toggled.connect(pipeline.set_paused)
    # a chosen app opened later: looked for off the interface thread
    apps.found.connect(lambda: sources.follow(captured(desktop.settings.value)))
    looking = QTimer(desktop, interval=APP_CHECK_MS)
    looking.timeout.connect(apps.look)
    looking.start()
    hearing = QTimer(desktop, interval=HEARING_MS)  # for the listening mark

    def heard() -> None:
        windows.heard(pipeline.hearing())
        if sources.sample_done:
            sample_ended()

    hearing.timeout.connect(heard)
    hearing.start()
    share_finished_days(tools.vocabulary, exchange)
    sharing = QTimer(desktop, interval=EXPOSURE_DAYS_MS)
    sharing.timeout.connect(lambda: share_finished_days(tools.vocabulary, exchange))
    sharing.start()
    checking = QTimer(desktop, interval=CHECK_EVERY_HOURS * 3_600_000)
    checking.timeout.connect(updates.check)
    checking.start()
    sender.send_waiting()  # reports kept from last time
    problem_sender.send_waiting()
    resending = QTimer(desktop, interval=RETRY_EVERY_SEC * 1000)
    resending.timeout.connect(sender.send_waiting)
    resending.timeout.connect(problem_sender.send_waiting)
    resending.start()

    hotkeys = system.hotkeys(
        {key: partial(desktop.hotkey_pressed.emit, key) for key in desktop.hotkeys}
    )
    desktop.hotkeys_taken(hotkeys.start())  # another app may have some
    # a game that is itself always on top comes to the front: the caption
    # windows go back above it (on the interface's thread)
    in_front = system.foreground_watch(windows.front_changed.emit)

    in_front.start()

    if not signed_in and not started.code_asked:  # the token refused before
        once_running(sign_in)  # (the first run asked for the code before the window)
    # learning syncs, and whatever waited since last time goes out, on it -
    # or, with nothing chosen to caption yet, in a sync session
    if not listen_then_sync(connection, listen, desktop.settings.value):
        not_listening()
    sources.follow(captured(desktop.settings.value))

    def stop() -> None:
        resending.stop()
        sender.close()
        problem_sender.close()
        hotkeys.stop()
        dictation_key.stop()
        dictating.stop()
        dictation_mic.stop()
        in_front.stop()
        looking.stop()
        hearing.stop()
        sharing.stop()
        checking.stop()
        speaker.close()  # a word being said stops
        pipeline.stop()
        connection.close()  # the last finished speech goes first; the summary is kept
        interface.close()  # the windows' choices saved
        desktop.close()
        store.close()  # after the last save: written before the app ends
        updates.at_exit()
        watchdog.stop()
        outbox.close()  # after the connection's last: what waits is written
        learning_store.close()  # last: after every write queued, the file closed now

    app.aboutToQuit.connect(stop)
    crashes.running = True
    code = app.exec()
    windows_deleted()
    sys.exit(code)


if __name__ == "__main__":
    main()
