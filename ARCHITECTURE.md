# Architecture

How polyglotic-desktop is organised: the module map, what each module
owns, and the rules between them. The standards behind it are in
polyglotic-hq: [ENGINEERING.md](../../polyglotic-hq/ENGINEERING.md) (ports
and adapters, the import rule) and [DOMAIN.md](../../polyglotic-hq/DOMAIN.md)
(bounded contexts, glossary, data and privacy). Structural decisions are in
[docs/decisions/](docs/decisions/). The protocol with the server is
polyglotic-server's [docs/protocol.md](../polyglotic-server/docs/protocol.md).
Last updated 2026-11-04 - the live-update timing rules are in (project 016);
`ports/` and `adapters/` added with the dictionary files (decision 0008);
Learning's rules (project 025); protocol v1's messages and the listening
session in `connection/` (project 022, decisions 0011 and 0012); caption
history and display rules (project 027); the outbox and sync sessions
(project 028, decision 0013).
The interface's rebuild beside today's `ui/` (decision 0031, 2026-11-07).

## Module map

```
src/polyglotic_desktop/
  core/              what the app does - plain Python, no I/O, no Qt
    shared/          where contexts meet: the events they publish, the IDs they share
      papers.py        the website's pages the app opens (privacy notice, tester agreement, Plus) and the agreement's version - one place (polyglotic-hq 185)
    listening/       sources, caption display state, caption history, live-update timing (v1)
      check.py         the "no captions?" check's rule: five links from connection to captions drawn, the first broken one named (096)
      failing.py       captions failing on the server: two finished captions failed in a row are said until a caption arrives (polyglotic-hq 158)
      unreachable.py   why the server can't be reached or isn't serving (offline, no answer, down, restarting, a failed session, blocked, not secure, the PC's clock, too many sessions on the account or failed sign-ins from this network), whose side each is on, and a restart said as one while the server comes back (polyglotic-hq 251)
      unstable.py      a connection that keeps dropping (two drops within 5 minutes, said until it has held 2 minutes) or has stalled (finished speech unanswered, or the server silent, 8 s too long) (polyglotic-hq 165)
      sources.py       a source: its id and category (never an app's name); its label on this PC - name and colour; the capture mode and what is captured (project 134)
      timing.py        the live-update timing rules, a pure state machine, and the caption modes (Steady, Quick preview, Live updates)
      pending.py       speech waiting to be sent, latest wins
      captions.py      caption updates from the server: live, finished, withdrawn; clauses, translations, word links
      history.py       caption history: updates applied in place, joins, withdrawals, stable keys, never blank
      settling.py      settled text: what a caption has shown for 3 s, or above its last two clauses, never changes; only what follows is taken from an update (decisions 0088, 0091)
      display.py       caption display rules: clause rows, second language, word links drawn, one-way layout
      transcript.py    the transcript written out as text, SRT or CSV
      settings.py      the user's listening settings: spoken language (each source's own, or Detect), targets (each source's own, or none),
                       spelling hints
      delays.py        each caption's delay (speech start and end to shown, the server's share) and the caption log's lines: one per caption event - sent, answered, shown, dropped and why - content-free, in logs/captions.log (polyglotic-hq 271)
      summary.py       a listening session's content-free summary: caption delay as seen, rewrite rate, dropped captions, minutes, lookups and saves counted;
                       per app vs whole system - time in each capture mode and at 0-3 apps, switches - and what the learner did (polyglotic-hq project 134)
      recheck.py       "Looks wrong?": a recheck's request and outcomes, what differs between two versions of a line, the content-free count (0030)
      problem_report.py "Report a problem" (alpha): the captions as shown in the last few minutes, each source's held speech, whose voices (275, 0067)
      warm_up.py       the server's warm-up notices, and when captions show one is over (Home's banner, polyglotic-hq 158)
      dictation.py     dictation - hold a key, speak, let go: each hold's pieces in order, the text typed (clauses joined, English fillers out, a space after), what the sign says; its source is `sources.DICTATION`, never a caption (polyglotic-hq 283, decision 0073)
      dictation_keys.py dictation's key as the learner chooses it - a key with modifiers, Right Ctrl alone, or modifiers alone, kept as text ("ctrl+alt+d"); Right Ctrl by default; why a key can't be one (types, Windows', every program's, Alt without Ctrl, the app's own) (polyglotic-hq 289, decision 0081)
      australian.py    English in Australian spelling, for dictation: colour, centre, organise, travelled; words whose spelling depends on their meaning left alone
    learning/        lookups, saved words, deck words (the line a word was learned from; decision 0026), the Anki file, word statuses, highlights, exposures
      vocabulary.py    Vocabulary: the learner's level, statuses, saved words, exposures; learning events; applying the server's
      levels.py        the level as a curve; statuses.py: statuses estimated or set, with a source
      saved_words.py   saved words, categories, finding them in a line
      highlights.py    unfamiliar words, as the learner's word introductions say (Off, a few per caption under the cap, every new word)
      languages.py     the languages being learned: each caption language's tier (full, basic, none yet), the one in use and the others, "Not now" (polyglotic-hq 262)
      exposures.py     exposures, once per finished caption, and the day each word was first heard; lookups.py: lookup context
      coverage.py      coverage: the tokens of each day's finished captions, known / in the deck / new as heard (on this PC, never sent)
      listening_time.py listening time per day and source category, from the gaps between finished captions (on this PC, never sent)
      bands.py         the words met by frequency band (top 1,000 ... 10,000, rarer) or level: known / in the deck / new / not heard yet
      anki.py          saved words as a CSV Anki imports
    lexicon/         dictionary entries, word split, readings, reverse lookup, meanings
    releases/        app version, update channel, feature flags from `welcome`
      updates.py       when to look for, download and apply an update; which channel to follow; the offer to restart into one (decisions 0017, 0090)
      milestones.py    the install's milestones as usage statistics: installed, updated, first caption shown (project 134)
  platform/          audio capture and speech detection, per OS
    speech_detection.py  Silero VAD on ONNX Runtime (model in data/, decision 0003); hears quiet audio raised (decision 0039)
    audio_buffer.py      each source's last 30s of audio, for cutting speech
    mic_bleed.py         the mic's audio vs what the PC played (decision 0004)
    opus.py              speech as Ogg Opus, 16kHz mono, 24 kbit/s (decision 0005)
    speech_pipeline.py   captured audio -> detection -> timing -> Opus -> waiting to send; silent in the sources that hear the PC's mix (and the mic) while the app says a word aloud (`hush`, decision 0077)
    replay.py            audio files played into the app through the capture port: headless runs, CI, the benchmark's load
    dictation_mic.py     the mic while the dictation key is held (`ports.capture.HeldMic`): opened at the press, closed 0.2 s after the release, a long hold cut at its quiet moment, each piece handed on as Ogg Opus in order; in memory only (polyglotic-hq 283, decision 0073)
    sample.py            Home's sample when nothing is playing: a FLEURS recording in the language learned (data/samples/, CC BY 4.0), played aloud (`SoundOut`, the OS's) and captioned as a source of its own (176)
    speaking.py          the `Speaker` port on a thread of its own over an OS's voices and output: voices listed in the background, a word made, its silence trimmed and played, the last click winning (polyglotic-hq 286, decision 0077)
    windows/         per-app capture, system audio, the mic (decision 0006); only main's os_adapters imports it (decision 0038)
      capture.py       WASAPI capture: one app, everything else (all but one app), the whole system, the mic; one app tried on Windows 10 2004+, with a trial that gives up on a PC where it fails (0076)
      apps.py          the apps with sound, for the app picker
      categories.py    app -> category (browser, video, call, game, other); the known-apps list's public names
      devices.py       outputs and mics, and Windows' defaults
      com.py           calling COM through ctypes
      keys.py          whether Esc, Backspace or a mouse button is held now, anywhere - read, not taken (a settings popover and the lookup card, without the focus)
      hotkeys.py       system-wide hotkeys (Ctrl+Alt+L/P/H) on a thread of their own, working over games; `HoldKey`, dictation's key or combination held - when it's all down and when any of it comes up: registered with Windows, or for Right Ctrl alone and modifiers alone their state read every 15 ms, another key with them a shortcut - no hook (283, 289, decision 0081)
      text_input.py    dictation's text typed into the program with the keyboard as Unicode key events, the clipboard untouched; the window that has the keyboard (283; the call that types waits for the guard - decision 0073)
      on_top.py        the caption windows back above a game that is itself always on top: whether one is in front, putting windows on top without activating them, and a watch on the foreground window (146)
      error_box.py     a plain Windows error box: the app couldn't start
      taskbar.py       whether Windows' taskbar is light or dark, for the tray icon's version (098); the ID the taskbar knows the app by - the installer's, the package's for the Microsoft Store's copy, else `Polyglotic.Desktop` from source (decisions 0051, 0056)
      package.py       whether this copy is an MSIX package - the Microsoft Store's - and the app ID Windows gave it (decision 0056)
      sound.py         a sound played aloud through Windows' PlaySound, from memory: the sample (176)
      voices.py        Windows' own voices: the OneCore voices listed and a word made into sound by WinRT's SpeechSynthesizer, played by winmm's waveOut (decision 0077)
      startup.py       starting with Windows: the user's Run key, the installed app in the tray (`--in-tray`; 176)
      process.py       when Windows started this process: the start from launch to the window, as `--check-install` reports it (136)
      system.py        which Windows this is (protocol.md's `os`, the version number feedback carries) and the data folder, `%APPDATA%\Polyglotic` (decision 0014)
  connection/        talks to the server: WebSocket, handshake, speech out, captions in
    protocol.py        protocol v1's messages as pydantic models; the speech frame (decision 0011)
    listening.py       timing decisions -> speech frames and `withdraw`; `caption_update` -> core's CaptionUpdate
    learning.py        Learning's events -> `learning` events; `learning_state` -> Learning's events (the open language's dictionary's only); daily exposures -> `exposures`
    app.py             what the app tells the server about itself: version and channel (the release's stamp), Windows
    sign_in.py         an invite code read as protocol.md says and redeemed for a device token (`POST /v1/redeem`)
    feedback.py        reports sent to `POST /v1/feedback` on a thread of their own; what waits sent again later (project 053)
    problem_reports.py alpha testers' problem reports: built, kept and sent to `POST /v1/problem-reports` on a thread of their own (275, 0067)
    session.py         a session: hello, settings, speech out, captions in, keepalive (decision 0012); or a sync session
    reconnect.py       after a session ends: back off and retry, or stop - by close code
    failures.py        why a try to open a session failed, from what the network said (a name not found, refused, a tunnel's 502/530, a proxy's page, TLS), and why the server closed one (1001, 1011) (polyglotic-hq 251)
    unanswered.py      finished speech not yet answered: kept in memory, sent again after a reconnect
    exchange.py        learning data, consent, usage, exposures: kept until `received`, sent on any session; consent rules (decision 0013); a sync cursor per language; a deletion made on any device applied, and what's done after it kept whatever the clock (decision 0023)
    milestones.py      the install's milestones kept between runs (an outbox note) and sent through the exchange, with consent (project 134)
    client.py          Connection: the listening session while listening, sync sessions otherwise (decision 0013)
  ui/                what the new interface stands on that isn't one window's - moves into ui_next at the rename (decision 0032)
    app.py             DesktopApp: the settings, the caption feed, the session's state, the commands (pause, lock and hide every caption window, my speech, feedback, quit), the hotkeys and the tray - what main builds and the windows follow
    settings.py        AppSettings: every setting with its default, read leniently, saved through the port (keys today's overlays used kept, for the migration and an older app)
    theme.py           the window theme's colours and heading face: Margin (default), Glaze or Signal - light, dark or like Windows (decision 0029); no app-wide stylesheet
    icons.py           the app icon and the tray's listening / idle / paused icons, drawn from the SVG masters in assets/icons (098)
    assets/            icons/: symbol A's SVG masters; fonts/: the themes' heading faces, each with its OFL text; translations/: the interface's compiled translations (.qm, built from translations/*.ts, not committed - decision 0034)
    interface_language.py the interface's language - the setting, else Windows', else English - and its translations installed at start (0034); the languages offered, the picker's order by own name, which are machine drafts (0087)
    learning.py        LearningTools: the vocabulary and dictionary the learning views share; at the start, on a thread of its own, reads the word split's data and what Words reads for every word met: facts, the bands' sizes, then each one's text for the search (136, polyglotic-hq 212, 220)
    captions.py        CaptionFeed: caption updates onto the Qt thread, into the history; exposures
    apps_with_sound.py the apps with sound, listed off the interface thread; Home's picker and main's sources share it (110)
    looks_wrong.py     "Looks wrong?": the comparison card with the best model's version, over the main window (0030)
    languages.py       the languages not offered as targets
    recorded_captions.py a developer's stand-in for the connection: a made-up conversation (the UI lab, tests)
    widgets.py         small controls today's dialogs use: labels, segmented choices
    first_run.py       the first run's screens one after another, each after the first with Back (`run`; `main.first_run` gives the steps; decision 0054)
    level_picker.py    the level picker (first run, and Words' Change)
    consent.py         the consent screen: what the service needs, and three choices off until yes (first run, and Account)
    delete_learning.py deleting the learning data: from the server, and from this PC only if ticked
    sign_in.py         signing in with an invite code (redeemed off the UI thread), and asking before signing out
    feedback.py        the feedback form: report a problem, suggest something - the log shown before it's sent (project 053)
    problem_report.py  "Report a problem" for alpha testers: every part ticked, with its size and Look; other people's voices said (275, 0067)
    dictation.py       `Dictating`: dictation in the running app - the key's holds, the mic, the pieces to the session, the answers typed into the window they were meant for, Esc, the sign's state; asks `main` for a listening session while it needs one (polyglotic-hq 283, decision 0073)
  ui_next/           the interface (decisions 0031 and 0032): every window and page; renamed ui once ui/'s pieces move in
    views/             what each surface shows, plain Python - no Qt
      captions.py      one app's captions (and "You", if shown) as lines: the original and one translation or none, kept in a caption history of their own (a transcript lists 1,000; Copy all and Save have the whole session, 137)
      scroll.py        following the newest line or held where scrolled back, measuring only the lines that show
      placement.py     where a caption window goes: presets, resizing anchored to the opposite edge, moving, snapping, kept on the screen (109's 10.1, 10.3); a joined window's place and equal columns (10.6)
      arrivals.py      how a new caption arrives: step and slide (D, the default: the text rises into place, the new caption in from below, at the speech's pace) or the step (B: the newest at full ink, the ones before a step back), B being D with Windows' animations off (F21; polyglotic-hq DECISIONS.md #104, 253, 267)
      app_choices.py   the apps a caption window can caption instead: found ones, then browsers and the main apps before they play (F12, polyglotic-hq 249)
      caption_window.py a caption window's own choices, kept by source; joined or separate, and the joined window's place; the session's look; the notice line
      migration.py     today's caption settings moved to each window's own, once: the first target language, my speech, the text size, the place (by source, not language); today's keys left as they are
      transcript.py    a transcript's own state: its app's finished captions (and "You"'s while its window shows them), search, following or scrolled back; its text size and rail kept per app; where it opens (109's section 3)
      lookup.py        W3, the lookup: what its card shows (hover, pinned, parts and Back, not in the dictionary, Chinese for it), its Learning commands, where it goes (109's section 6)
      speech.py        hearing a looked-up word: the language it's said in (the word's, never the interface's), the voice that says it, its own pace then slower (polyglotic-hq 286)
      home.py          Home's views: the state line's rules, and the app picker - the captioned apps' rows (at most 3), everything else beside one app (DECISIONS.md #59), the apps that could be added, everything the PC plays (109's sections 5 and 7)
      panels.py        the three shared panels' views - Languages (the session's; one window's in a transcript's rail), Timing, Look: one value each, every panel bound to it told of a change (109's section 4)
      lab.py           Settings > Captions > Lab's experimental values, one `CaptionLab` in the shared look, saved as one setting, each slider's measured range (polyglotic-hq 284)
      pacing.py        captions arriving together let into a window the Lab's gap apart, in order, none dropped, none waiting past the longest wait for text (polyglotic-hq 284)
      presets.py       the ten colour presets (polyglotic-hq 248's section 6), which one a look's colours are, exact colours as typed, WCAG's contrast - and a label colour made readable on any panel
      words.py         Words' rows: a word's text from the dictionary or what was saved, looked up only when its row shows; a search; the level in words (109's section 7)
    caption_layout.py  the caption layout engine: lines laid out per caption x width x text size, painted directly, marks at paint time
    caption_surface.py one app's caption lines painted - a plain widget caption windows, transcripts and a joined window stand on
    caption_window.py  W1, the caption window: the canvas, the hover strip (label, word links, lock, settings, close; A- / A+ in its settings popover), the notice line, Back to live (109's section 2; the Strip went in polyglotic-hq 272); words under the mouse for the lookup (a press on a word looks it up, a drag selects a phrase); never takes the focus
    settings_popover.py the caption window's settings beside its settings button: spoken language, language, lines already in it, my speech, timing, text size, ...; a joined window's column's, and the joined window's own; non-modal, never takes the focus
    joined_window.py   W1j, the joined window: the apps' caption windows as its columns, side by side, equal widths or as the dividers were dragged (284); one place, lock, notice line and fade for the whole window (109's 2a, 10.6)
    caption_windows.py the caption windows, one per app captioned (at most 3): captions to each, their choices saved, what they ask of the session; joined and separated
    caption_marks.py   what a caption window marks at paint time: saved words, unfamiliar words and words in the deck (Learning), word links; a lookup's action forgets only the lines holding its entry
    lookup_card.py     W3, the lookup card: one painted card for every caption window - hover after the mouse rests, pinned by a click, the actions, parts and Back, the context line, the speaker that says the word; never takes the focus (109's section 6)
    word_speech.py     the card's "say it" over the `Speaker` port: says or stops the word, its state, no voice and Windows' speech settings; the app's own sound handed to the captions' hush (polyglotic-hq 286)
    style.py           the window theme's colours as tokens (today's `ui.theme`, handed over by `main`) and a stylesheet scoped to one window - never the app's; the text size, Windows' times the app's own (`text_scale`, `px`: decisions 0033 and 0084)
    controls.py        small standard controls: a card, a setting's row, a row of choices, a switch, a colour choice, a status dot
    caption_preview.py Settings > Captions > Look's live preview: two made-up captions over the app's own painted still, drawn by the caption windows' engine in the look now - never a screen capture
    lab_panel.py       Settings > Captions > Lab: the experimental controls, a preview of their own and Reset the lab - a card in its own file (polyglotic-hq 284)
    colour_controls.py the look's colour controls: the presets as tiles (as many to a row as fit) and one colour exactly - its swatches, a hex field and Pick... (the colour dialog)
    glyphs.py          the caption windows' icons - lock, settings, close, more, the mic - drawn with QPainter in the manner of Windows' icon font, which other OSes lack (polyglotic-hq 179)
    fonts.py           each OS's own fonts, after Windows' in every font list (none on Windows: its lists are as they were)
    home.py            Home: the state line, the app picker, the caption windows' commands, feedback - in a centred column at most 720 px wide (Languages and Timing moved to Settings > Captions, polyglotic-hq 261)
    main_window.py     W4, the new main window: the sidebar (Home, Words, Learning, Account; Settings and Help at its foot; Quit), a page at a time, minimum 960 x 680 (kept to a small screen, never under 760 x 520), its theme its own stylesheet
    panels.py          the shared panels - Languages (Settings' Speech), Timing, and the look's Look, Word links, Behaviour and Reset - each one widget bound to one view, in Settings > Captions and a transcript's rail; each setting's line under its name in Settings, on hover in the rail
    words_page.py      Words (today's Vocabulary, renamed): a section per language learned (`LanguageSection`; one today, simply open; several fold under a heading with the count, left as the learner left them - `OpenLanguages`, polyglotic-hq 250), each that language's words (`LanguageWords`): the level, what you've heard (`heard_card`: words met, coverage of the last 7 days, listening time, and the bands - `word_bands`; the summary line under the title), words you keep hearing, your words, saved words and their categories, the Anki export; a word pins the caption windows' lookup card
    word_table.py      a list of words as a painted table as tall as its rows (the page scrolls): a row's text looked up when it first shows, its actions as buttons, the keyboard's too
    learning_page.py   Learning: a card per language being learned (its dictionary's tier and what that gives, its level, use it instead, stop), Learn another language, Word introductions (Off · A few per caption · Every new word, with a caption drawn with the marks), Words and Anki, Account's "Delete learning data…" (polyglotic-hq 262)
    account_page.py    Account: sign in or out and the account ID, what's shared, deleting learning data, feedback - today's commands, wired by `main`
    settings_page.py   Settings: three sections at its top (polyglotic-hq 248, 261) - Captions (every caption window's settings, the shared panels), Learning (a way to the Learning page) and App (appearance, the app's language, the hotkeys, updates, About and the third-party notices); a caption window's "All caption settings..." opens it on Captions
    help_page.py       Help: the live "no captions?" check, set-up and questions in the new interface's words, a report with the check's result
    languages.py       languages by name, for the language chip and the language spoken; the languages to pick; dictation's - every one the speech model takes, Chinese with the characters it types (283)
    transcript_window.py W2, the transcript window: the app strip, the lines painted on the layout engine (only what shows; a layout cache of its own), search, Back to live, "Looks wrong?", the lookup (the caption windows' card), copy and save, the settings rail with the session's panels (a popover over the list below 700 px); dressed in the new interface's window theme (`style`)
    transcripts.py     the transcripts, one per app captioned, collecting from the start: each following its caption window's language and my speech, its window opened on demand (Open transcript, the tray), their rails' panels bound to the session's views, their choices saved
    dictation_sign.py  dictation's sign: a pill above the taskbar - Listening with the mic's level, Working, then why nothing was typed, naming the key; which key to hold as dictation's turned on; never takes the focus, clicks pass through (283, 289)
    dictation_key.py   dictation's key in words ("Ctrl + Alt + D"), why one is refused, and Settings' box that listens for the key pressed (289, decision 0081)
    save_folder.py     where every save dialog opens (Save transcript as..., both Anki exports): the folder saved to last, kept in the settings, or Documents - never the install folder an update replaces (polyglotic-hq 244)
  perf/              measuring the interface
    budgets.py         the budgets the user agreed (DECISIONS.md #53): one place for the numbers tests and the lab check
    spans.py           named spans, off unless recording (the lab); timings as JSON - names checked to be constants, never text
    watchdog.py        logs any stretch of interface-thread work over 50 ms by `file.py:function` and duration; on in normal use (`main` starts it)
  adapters/          storage and other infrastructure behind the ports
    sqlite_dictionary.py  the dictionary files (decision 0009); the learner's never stops the app (199)
    japanese_split.py     Japanese words and their dictionary forms, by Sudachi (the basic Japanese pack, decision 0035)
    spaced_split.py       words of a spaced language with simplemma's lemma (the basic Spanish pack, decision 0035)
    sqlite_learning.py    the learner's own learning data on this PC (decision 0010); what they heard, and daily counts kept 8 weeks (0041); one that can't be read set aside and kept (polyglotic-hq 206); a row it can't read left out and kept, too many refused (207); the level kept beside it too, so a store set aside keeps it (0048)
    background_learning.py  that store on a thread of its own: Learning's saves never wait on the disk; reads wait for the writes before them (110)
    anki_package.py       the Anki deck file (.apkg), with genanki (decision 0028)
    json_settings.py      the user's settings, one JSON file
    windows_credentials.py  the device token in Windows Credential Manager; signing out keeps the install id (0080)
    sqlite_outbox.py      what waits to be sent to the server, and the consent choices (decision 0013); an unreadable file set aside
    background_outbox.py  that outbox on a thread of its own: the consent choice and every event are written in order, never on the interface thread; reads wait for the writes before them (144)
    velopack_updates.py   the installer's hooks at start, and updates through Velopack (decision 0017)
    feedback_files.py     reports waiting to be sent, one JSON file each (apart from the content-free outbox)
    problem_report_files.py alpha testers' problem reports waiting to be sent, each as its request body (275)
    app_log.py            the app's log as a report attaches it: the newest part, the user's folder hidden
    signed_feed.py        the update feed checked against our signature, for its channel, before Velopack reads it (decisions 0019, 0020; off until main.FEED_KEYS is set)
  ports/             the interfaces core needs from outside, and the plain types that cross them
    capture.py         AppList, AudioCapture, SourceCategory, AppCaptureSupport and AppCaptureTrial (0076) - what capture needs from the OS; HeldMic, MicPiece - the mic while the dictation key is held (283)
    mic_bleed.py       MicBleedCheck - the mic's audio vs what the PC played
    dictionary.py      DictionaryFile - one dictionary's entries on disk
    word_split.py      WordSplit, SplitWord - the words in a line of one language, and the dictionary forms to look them up as
    learning.py        LearningStore - the learner's own learning data on this PC
    settings.py        SettingsStore - the user's settings, remembered between launches
    credentials.py     CredentialStore, DeviceCredentials - the install id and device token
    outbox.py          Outbox, Waiting - what waits on the PC to be sent to the server
    consent.py         ConsentStore, ConsentChoice - the user's consent choices
    updates.py         Updater, Update - the installer's updates
    feedback.py        WaitingReports, Report - feedback kept on the PC until sent
    problem_reports.py WaitingProblemReports, ProblemReport - an alpha tester's report, with captions and audio if left ticked (275)
    system.py          OnTop, ForegroundWatch, Hotkeys, HoldKey, TypeText, KeyboardWindow, KeyState, LightTaskbar, TaskbarIdentity, StorePackage, OsVersion, DataFolder, ErrorBox, LaunchClock - what the app needs from the OS beyond audio (decision 0038)
    startup.py         StartWithWindows - the app in the tray at sign-in, once the learner says yes (176); `IN_TRAY`, the switch it starts the app with
    speaker.py         Speaker, Voice - a word said aloud in one of the PC's voices, and when the app's own sound plays (286, decision 0077)
  main.py            the one place that wires everything together (the connection, the outbox and the first-run screens too); `os_adapters` picks the OS's adapters, imported only there (decision 0038)
  harness.py         a developer's command line: capture, sign in, listen to a server and print captions (no UI); consent, learn, sync, delete
docs/
  decisions/         one page per structural decision
  rule-cases/        the rules as JSON cases a later port must pass: timing, level curve, highlights, word split, display (decision 0022)
tools/
  dictionaries/      builds the dictionary files from pinned sources (decision 0009); entry IDs
    registry/        the entry IDs that aren't their key's hash (decision 0007)
  protocol_examples.py  copies and checks polyglotic-server's protocol examples (decision 0011)
  rule_cases.py      writes and checks docs/rule-cases/ from the rules (decision 0022)
  mypy_platforms.py  mypy as macOS and Linux see the code: only Windows' own modules may fail (decision 0038)
  linux_qt_libs.sh   Qt's system libraries for the Linux runner, unpacked without root (decision 0038)
  private_desktop.py real windows on a Windows desktop of their own, never shown: a command run there, its windows read from outside, pictures by its own grab() (docs/real-windows.md)
  window_icon.py     a window's icon as Windows draws it (title bar, taskbar, Alt-Tab), read from outside its process, and whether it's the app's (docs/real-windows.md)
  busy_pc.py         whether the PC is saturated now: a budget test or lab state over budget gets more tries only then (decision 0040)
  learner_start.py   the app's start with a made-up learner of many words met, timed from `main()` to the window: CI's start gate on the real CC-CEDICT (decision 0046)
  ui_lab/            the UI lab: every state offscreen, a PNG and a timing JSON each, the code checks (clipped and small text, contrast, names, keyboard, scrollbars, squashed layouts) and golden images (goldens/, approved with `approve`); new parts gated on all three, today's recorded (decision 0031); `judge` writes the judge's kit - contact sheets, findings, timings, a checklist - for the review loop in JUDGE.md; `seen` finds which strings each state shows, the order of a reviewer's sheet (polyglotic-hq 294)
  i18n/              the interface's strings read from the code into translations/*.ts, compiled to .qm (`python -m tools.i18n update`; decision 0034); `draft` hands a language's untranslated strings to a drafter and checks its answers back in (`keep.py`: names, counts, tags, forms; polyglotic-hq 294); `sheet` makes a reviewer's spreadsheet
  package/           building the app testers install: the release stamp (decision 0015); PyInstaller one folder, checked (decision 0016); publishing it, the feed signed as served (decision 0020); the daily feed check, each channel against its latest Release; what a Release run does and a build promoted to another channel by repacking it, not rebuilt (`release_plan`, `promote`, `pack.sh`; decision 0044); a version's notes from RELEASE-NOTES.md (`release_notes`); the same build packed again as the Microsoft Store's MSIX, with the Windows SDK's tools pinned (`msix`; decision 0056)
translations/        the interface's translation files (.ts) - what translators and reviewers work in (README.md there; decision 0034)
build/               git-ignored: downloaded sources and built dictionary files
tests/               pytest; core tested through fakes, no devices or models
  protocol_examples/ a copy of the server's protocol examples, with its manifest (decision 0011)
```

Each package's docstring says what belongs in it.

## What each module owns

| Module | Owns | Never |
|---|---|---|
| `core` | The domain rules of each context the app runs, in the glossary's words | I/O; Qt; imports of `ui`, `platform`, `connection`, `adapters`, `main` or infrastructure libraries |
| `core.shared` | Events contexts publish ("caption finished", "word looked up") and shared IDs (caption id, entry ID). Small immutable types - including what Lexicon tells Learning about the words in a line (`WordInLine`, `EntryFacts`). | Logic; imports of any context |
| `core.<context>` | That context's model and rules (DOMAIN.md's table) | Imports of another context; it reacts to others' events instead |
| `platform` | Turning one app's audio, the whole system's or the mic into speech segments | Caption rules; imports of `ui` or `connection` |
| `connection` | The WebSocket per listening session, the handshake, protocol messages <-> core, reconnecting, the offline event buffer; usage events only with consent; the server's address checked (TLS to anything but this PC, `addresses.py`) | Caption rules; imports of `ui` or `platform` |
| `ui` | Showing core's state in Qt and passing the user's actions to core | Domain rules; imports of `platform` or `connection` |
| `ui_next` | The new interface (decision 0031): what `ui` owns, rebuilt; `views` is plain Python | Domain rules; imports of `ui`, `platform` or `connection`; Qt in `views` |
| `perf` | The interface's budgets, and measuring its time - names and durations only | Caption text or words; imports of the interface |
| `ports` | Every interface core needs from outside (`typing.Protocol`s: `AppList`, `AudioCapture`, `MicBleedCheck`, `DictionaryFile`, `LearningStore`, `CredentialStore`, `SettingsStore`, `Outbox`, `ConsentStore`, `Updater`) and the plain value types that cross them (`SourceCategory`, `EntryRecord`, `DeviceCredentials`, `Waiting`, `ConsentChoice`, `Update`) | Imports of anything else in the package; infrastructure libraries |
| `adapters` | Storage and other infrastructure behind the ports: the dictionary files, the learner's learning data and the outbox (SQLite), the device token (Windows Credential Manager), the user's settings (JSON), updates (Velopack) | Domain rules; imports of `ui`, `connection` or `platform` |
| `main` | Update check first, then building platform, connection and UI, handing core its implementations, connecting them | Logic of its own |

## The rules between them

| Rule | Checked by |
|---|---|
| Layers: `main` (and the developer's `harness`) → `ui` \| `ui_next` \| `connection` \| `platform` \| `adapters` → `perf` → `core` → `ports`; nothing imports upwards | import-linter `layers` |
| `ui`, `ui_next`, `connection`, `platform` and `adapters` don't import each other | import-linter `layers` (the `\|`) |
| The new interface's views use no Qt | import-linter `views-no-qt` |
| The new caption surfaces keep to their budgets at 1,000 captions | `tests/ui_next/test_budgets.py`, `test_transcript_budgets.py`; CI's UI lab job (`tools/ui_lab`, every new part's state) |
| An hour of captions, once the windows and transcripts are full, grows the app's private memory by at most 3 MB (`perf.budgets.MEMORY_HOUR`) | `tests/ui/test_memory_over_an_evening.py`, a synthetic evening on the interface as `main` wires it (Windows; decision 0049) |
| Words opens, and its first search answers, within budget (50 ms) for a learner with 10,000 words met | CI's UI lab job: the `words_met_*` states (`tools/ui_lab/pages.py`; 30,000 recorded, not held; polyglotic-hq 212, 220); `tests/ui/test_words_read_ahead.py` (the first search reads nothing) |
| Every string the interface shows reaches the translation files; English's counts read as English; translations keep their placeholders, counts, tags and forms; every language offered has its file, and every file is offered | `tests/ui/test_translations.py` (`tools/i18n`, decision 0034) |
| `perf` records names and durations only: span names are constants; the watchdog names code, never its data | `tests/test_perf.py` |
| `core` and `ports` import no Qt, audio, Windows API, network, storage or vendor library | import-linter `core-no-infrastructure` (the list is in `pyproject.toml`) |
| Contexts inside `core` don't import each other; they meet in `core.shared` | import-linter `contexts-independent` and `shared-imports-no-context`; `tests/test_layout.py` keeps the lists in step with the folders |
| `core` and the protocol (`connection`) are fully typed | mypy, strict for `core` and `connection` (normal elsewhere) |
| Only Windows' own modules (`platform/windows`, the Windows credential store) are imported by `main` alone, and only they may fail to type-check as macOS and Linux see them | import-linter `os-in-one-place`; `tools/mypy_platforms.py` in CI (decision 0038) |
| Tests that need Windows itself say so, and are skipped elsewhere; the rest pass on Linux | the `windows_only` marker (`tests/conftest.py`); CI's Linux job (`Checks (Linux)`, Qt's libraries from `tools/linux_qt_libs.sh`) |
| The app's messages match the server's protocol examples | `tests/test_protocol.py`, against a copy kept by `tools/protocol_examples.py` (decision 0011) |
| The rules give the answers in `docs/rule-cases/` | `tests/test_rule_cases.py`, reading only the JSON (decision 0022) |
| Usage events only from the server's tracking plan, only with consent | `connection.exchange` keeps usage events and exposure counts only with their consent (`tests/test_exchange.py`); the plan itself: review, for now (it lives in polyglotic-server) |
| Flags are read only through one `flags` module | Review (the module isn't built yet) |
| Audio and caption text never logged; app names leave the PC only as categories - a known app's public name only in consented usage statistics (DECISIONS.md #30) | Review (checklist item 9); `tests/test_session_summary.py` and `tests/test_windows_capture.py` (only listed names, never with speech) |

Loosen a contract only with a decision record saying why.

## The interface's rebuild (decisions 0031 and 0032)

The interface was rebuilt, beside today's `ui/`, in Qt Widgets done
well (polyglotic-hq project 108's audit, DECISIONS.md #53). Since the
switch-over (decision 0032, 2026-11-07) it is the app:
- **`main` starts the new interface:** the caption windows
  (`ui_next.caption_windows`, one per app captioned, at most 3, or one
  joined window), a transcript window per app (`ui_next.transcripts`)
  opened from them and the tray, and the new main window
  (`ui_next.main_window`: Home, Words, Account, Settings and Help). No
  app-wide stylesheet: each window has its own. Today's tray and dialogs
  stay; `main` wires the new parts to them. `DesktopApp` (`ui.app`) keeps
  the app's state - the session's, the commands, the tray - and the
  windows follow it; today's main window, overlays and pages are gone.
  The developer switch
  `--next-interface` is accepted and ignored until the first release
  after it, then removed.
- **`ui_next/` sits in `ui/`'s layer;** neither imports the other.
- **`ui_next/views/` is plain Python, no Qt:** what each surface shows,
  tested without Qt. Qt widgets draw a view and hand actions back to it.
- **One caption layout engine** for caption windows and transcripts:
  newest first, only what shows, cached per caption x width x text size
  for the lines each surface can show again (a caption window's 150, a
  transcript's last 300 shown; polyglotic-hq 239); text painted directly;
  marks drawn at paint time.
- **`perf`** (spans, the interface-thread watchdog, timings as JSON) sits
  between the interface and core, so `ui`, `ui_next` and `main` can use
  it; the budgets live in `perf.budgets` and are tests.
- **The UI lab** (`tools/ui_lab/`) drives states offscreen and writes a
  PNG and a timing JSON per state, and runs the code checks on every
  window a state shows (`checks.py`: clipped text, text under 12 px,
  contrast, accessible names, keyboard reach, horizontal scrollbars,
  squashed layouts), and compares each new part's picture with its
  approved golden (`goldens.py`; `goldens/` holds the PNGs, made on the
  user's PC where CI runs); CI gates the new parts' budgets, checks and
  goldens and records today's interface's numbers and findings. A
  timing over budget is retried once, and up to twice more while the PC
  measures saturated (`tools/busy_pc.py`, decision 0040).
- **The start's budget** is held twice: `--check-install` with an empty
  learner, and the UI lab job's start gate with a made-up learner of
  30,000 words met on the real CC-CEDICT (`tools/learner_start.py`,
  decision 0046).

## Not placed yet

- **The `flags` module:** Releases owns flag values, but any context may
  need one, and contexts can't import `core.releases`. Decide with the
  first flag.

## Decisions

- [0001 Ports and adapters on the desktop, checked by import-linter](docs/decisions/0001-ports-and-adapters.md)
- [0002 One package per bounded context; contexts meet in core.shared](docs/decisions/0002-bounded-contexts.md)
- [0003 The speech-detection model is committed, pinned by its checksum](docs/decisions/0003-speech-detection-model-committed.md)
- [0004 Mic bleed is checked against the whole system's audio](docs/decisions/0004-mic-bleed-reference-is-system-audio.md)
- [0005 Speech is sent as Ogg Opus at 24 kbit/s, encoded by libsndfile](docs/decisions/0005-speech-as-ogg-opus-24k.md)
- [0006 Windows capture is our own WASAPI code through ctypes](docs/decisions/0006-windows-capture-with-own-ctypes-wasapi.md)
- [0007 Stable entry IDs: a hash of the entry's first key, plus a registry of exceptions](docs/decisions/0007-stable-entry-ids.md)
- [0008 Every interface core needs in `ports/`; storage in `adapters/`, as on the server](docs/decisions/0008-ports-and-adapters-packages.md)
- [0009 Dictionary files: SQLite, built from pinned sources, not committed](docs/decisions/0009-dictionary-files.md)
- [0010 The learner's own learning data on the PC: one SQLite file, behind a port](docs/decisions/0010-learning-data-in-sqlite.md)
- [0011 Protocol messages as pydantic models, tested against a checked copy of the server's examples](docs/decisions/0011-protocol-models-and-a-checked-copy-of-the-examples.md)
- [0012 The server connection is `websockets` on asyncio, in a thread of its own](docs/decisions/0012-websockets-on-asyncio-in-a-thread.md)
- [0013 What waits for the server is kept in an outbox on disk; sync sessions open on threads of their own](docs/decisions/0013-outbox-and-sync-sessions.md)
- [0014 The user's data lives in `%APPDATA%\Polyglotic`, outside the installer's folder](docs/decisions/0014-user-data-in-roaming-app-data.md)
- [0015 A release's version comes from its git tag; the server and update addresses are constants in code](docs/decisions/0015-version-from-the-tag-addresses-in-code.md)
- [0016 The app is packed by PyInstaller as one folder, built and checked by `tools/package/build.py`](docs/decisions/0016-pyinstaller-one-folder-build.md)
- [0017 Updates: Velopack behind a port; core decides when; applied at the next start](docs/decisions/0017-updates-through-velopack.md)
- [0018 Releases are built, packed and published by a tag-only workflow, and the public feed is checked daily](docs/decisions/0018-release-workflow.md)
- [0019 The signed update feed: Ed25519, checked by the app before Velopack reads it - built, switched off](docs/decisions/0019-signed-update-feed.md)
- [0020 The update feed is signed and recorded as the storage serves it, with its channel inside the signature](docs/decisions/0020-feed-signed-as-served.md)
- [0021 The installer is built and tried on main, not on every pull request](docs/decisions/0021-installer-built-on-main-not-pull-requests.md)
- [0022 The app's rules are written down as shared test cases, in JSON, for any later port to pass](docs/decisions/0022-rules-as-shared-test-cases.md)
- [0023 Learning done after a deletion counts as after it, whatever the PC's clock](docs/decisions/0023-learning-after-a-deletion-whatever-the-clock.md)
- [0030 "Looks wrong?": a line checked with the best model, over the listening session, nothing kept](docs/decisions/0030-looks-wrong-checked-with-the-best-model.md)
- [0031 The interface is rebuilt in Qt Widgets, beside today's, on plain-Python views](docs/decisions/0031-interface-rebuilt-in-qt-widgets-beside-today.md)
- [0032 The switch-over: the new interface is the app; today's main window and overlays go](docs/decisions/0032-switch-over-new-interface-is-the-app.md)
- [0034 The interface is translated through Qt's .ts files, read from our own wrappers, with English's counts in a file too](docs/decisions/0034-interface-translations-qt-ts-files.md)
- [0038 The OS's adapters are picked in one place, at start, and nothing else imports them](docs/decisions/0038-the-os-picked-in-one-place.md)
- [0039 Speech detection hears quiet audio raised to -20 dBFS; the audio sent is unchanged](docs/decisions/0039-speech-detection-hears-quiet-audio-raised.md)
- [0044 One build per tag: promoted to another channel by repacking it, not rebuilt; a hotfix tag publishes only where it's sent](docs/decisions/0044-one-build-per-tag-promoted-not-rebuilt.md)
- [0045 The install-and-update test runs by hand in the PC runner's own Windows account, then uninstalls](docs/decisions/0045-install-test-in-the-runners-own-account.md)
- [0046 CI holds the start to its budget with a made-up learner of 30,000 words met](docs/decisions/0046-the-start-gated-with-a-big-learner.md)
- [0048 The learner's level is kept beside the learning store as well as in it](docs/decisions/0048-the-level-kept-beside-the-learning-store.md)
- [0049 An hour of captions may leave at most 3 MB behind: a memory budget CI holds](docs/decisions/0049-an-hour-of-captions-leaves-little-behind.md)
- [0051 Windows knows the app by one taskbar ID: the installer's when installed, `Polyglotic.Desktop` from source](docs/decisions/0051-one-taskbar-id-the-installers-or-polyglotic-desktop.md)
- [0056 The Microsoft Store gets the same build, packed again as an MSIX; the Store updates that copy](docs/decisions/0056-the-store-gets-the-same-build-as-an-msix.md)
- [0057 The installer gives the app and its shortcuts one taskbar ID: the pack ID's `.Desktop`](docs/decisions/0057-the-installer-names-the-app-polyglotic-desktop.md)
- [0066 A change settles before it leaves the interface: shown at once, saved and sent 300 ms after the last](docs/decisions/0066-a-change-settles-before-it-leaves-the-interface.md)
- [0073 Dictation: a source of its own on the listening session, one piece per hold, typed into the program with the keyboard](docs/decisions/0073-dictation-rides-the-listening-session-and-is-typed.md)
- [0081 Dictation's key is the learner's choice; Right Ctrl alone is read, never hooked](docs/decisions/0081-dictations-key-is-the-learners-choice-right-ctrl-is-read-not-hooked.md)
- [0077 A looked-up word is said in Windows' own voices, behind a `Speaker` port, and kept out of the captions](docs/decisions/0077-a-word-said-in-windows-own-voices-behind-a-speaker-port.md)
- [0080 The install id outlives signing out, and each server keeps its own sign-in](docs/decisions/0080-the-install-id-outlives-signing-out.md)
- [0090 A downloaded update is offered on Home and in the tray, with Restart now](docs/decisions/0090-a-downloaded-update-is-offered-with-restart-now.md)
- [0091 Two hearings are lined up by the fewest words passed over](docs/decisions/0091-two-hearings-are-lined-up-by-the-fewest-words-passed-over.md)
- Protocol version 1, with the app deciding live-update timing:
  polyglotic-server's decision 0003 (the server owns the protocol).
