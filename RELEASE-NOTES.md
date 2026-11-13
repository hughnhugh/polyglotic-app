# Release notes

What changed in each version of Polyglotic, in plain words for the people
who use it. One source, used four times (polyglotic-hq RELEASING.md
section 10): the GitHub Release's text above the SHA-256s (`release.yml`),
the app's What's new, the website's What's new and the Discord post.

- **A pull request people would notice** adds one line under Unreleased,
  in New, Better or Fixed (the pull request template asks; "none" is fine
  for the rest). Say what changed for the learner, not how it was done.
  A server change people would notice (a better translator, a new
  language) gets a line too, in the next app release.
- **No promise the work doesn't back:** no speed or accuracy figures
  unless polyglotic-hq says they can be claimed, and nothing about privacy
  beyond what the privacy notice says (polyglotic-hq project 181's
  CLAIMS-V2.md).
- **At a release,** Unreleased moves under `## X.Y.Z - YYYY-MM-DD` in the
  release's prep pull request, before the tag; the three empty groups stay
  for the next line. A tag without its section doesn't release
  (`python -m tools.package.release_notes vX.Y.Z`).

## Unreleased

### New

- Polyglotic's own words in Spanish, French, German, Portuguese (Brazil),
  Italian, Japanese, Korean, Vietnamese, Indonesian, Turkish, Russian,
  Polish, Dutch, Ukrainian, Filipino, Thai, Hindi, Malay and Czech:
  Settings > App language, or "Like this PC" picks one when Windows is in
  it. They're drafted by machine and not yet
  checked by native speakers - Settings says so, with "Tell us what reads
  wrong" beside it.
- When an update has downloaded, Home says so - "Version X is ready.
  Restart to install it." - with what's new in two lines, Restart now and
  Later; the tray's menu offers it too. Polyglotic never restarts by
  itself: Later leaves it for the next time it starts. Settings - App -
  Updates now says what Check now found.
- Hear a word: the speaker beside Close on a word's card says it aloud
  in one of Windows' own voices, and again more slowly on the next click
  (R does the same in Polyglotic's own windows). It's said on your PC -
  nothing is sent - and it's left out of your captions. If Windows has no
  voice for the word's language, the card says how to add one, free, in
  Windows' Settings.
- Text size: Settings > App > Text size makes Polyglotic's own words
  smaller or larger - Settings, Words, Help, a word's card and its
  explanations, menus, and the buttons on caption windows and transcripts
  - at once, on top of Windows' own text size. Captions keep their own
  size (A- and A+ on each caption window and transcript).
- Dictation (preview) is held on Right Ctrl, a key nearly every keyboard
  has, or on any key or combination you choose: in Settings - App, click
  the key and press the one you want - F9, Ctrl + Alt + D... If a key
  can't be used (it types, Windows keeps it, another program has it), it
  says why and keeps the one you had. A key you already chose stays.

- On Windows 10 version 2004 or later, Polyglotic now tries captioning
  apps one by one, as on Windows 11. If Windows on your PC can't, it says
  so once and captions everything the PC plays, as before; Try apps again
  on Home tries once more, and so does each Windows update.
- Testing the alpha? Report a problem - the flag on a caption window's
  top bar, the tray's menu, Home, Account and Help - can now send what
  was shown and heard in the last few minutes, so we can see the problem
  again. You see each part first and can untick it; reports are deleted
  after 30 days.
- A shorter tester agreement: seven points. The app asks you to agree to
  it once more.
- Click a word in a language you aren't learning - Japanese in a
  Japanese stream - and its card asks once whether you're learning it
  too: Learn it too adds it to Learning; Not now doesn't ask again. In a
  language with no dictionary yet, the card says so rather than "Not in
  the dictionary".
- A Learning page, beside Words: the languages you're learning and what
  each one's dictionary gives, your level, and Word introductions - Off,
  A few per caption or Every new word - with what the marked words mean
  and where they go. "You're learning" and "Common words only" moved
  there.
- Ten colour presets for the caption windows, in Settings - Captions:
  Classic (as before), Broadcast, Teletext, Ember, Violet, Forest, Paper,
  Quiet, High contrast and Clear (safe for every kind of colour
  blindness). Change any colour after: type its exact value, or Pick… it.
- A live preview at the top of Settings - Captions shows two captions as
  your caption windows will: every change to the colours, panel, font or
  word links shows there at once.
- Word links can be Arrows again: a curve joins each word to its
  translation, as well as their shared colour (Settings - Captions - Word
  links).
- Pick the app a caption window captions from the window itself: click
  its name, or Captioning in its settings. Browsers and the main apps are
  listed even before they play, and start captioning when they do.
- In every timing, a small loading bar under the newest caption shows
  that speech is being heard and its caption is on its way - for your own
  speech too. With Windows' animation effects off, it stands still.
- Choose how new captions arrive, for every window, in Settings - Captions
  - Behaviour: Slide in (the default) or Appear.
- Each caption window has its own spoken language in its settings: a
  Chinese stream in one window and an English call in another are each
  heard as what they are, and Detect is there for mixed talk. Lines
  already in a window's language can be shown in another language from
  the same settings.
- Longest wait for text, in Settings - Captions - Timing: how long anyone
  can talk before you see text, in every timing - from 2 to 6 seconds, 3
  unless you change it. A smaller number means more updates.
- A caption window opens as soon as you choose an app, or everything your
  PC plays, and says it's waiting for audio until the first captions come.

### Better

- The app's language in Settings is a list, each language by its own
  name, none pinned first. A language whose text was drafted by machine
  and not yet checked by a native speaker says "Machine draft" beside
  it, with "Tell us what reads wrong".
- Live updates: a long stretch of speech now finishes in pieces, at a
  pause or a breath, as it does in Steady. The words you've already read
  stay as they are instead of all being rewritten when the speaker
  finally stops.
- Captions settle: words a caption has shown for about three seconds,
  and lines above its last two, no longer change when Polyglotic hears
  the speech again - their translations stay too. Only the newest words
  are still corrected.
- The line saying Cantonese and Vietnamese speech is captioned less
  accurately is gone from Settings > Captions, from each caption
  window's settings and from Help's questions.
- Polyglotic no longer asks which language you're learning before it
  opens. It starts translating into your PC's language when captions can
  be translated into it (else English) and detects the language spoken;
  choose the language you're learning on Learning, and change any of
  them in Settings whenever you like.
- It doesn't ask your level before it opens either. Until you set it,
  words count as known up to a middle level (HSK 3, or the 3,000 most
  common English words), and a quiet line on Home offers to set it.
- Language lists start with your PC's own language, then every other
  language by name; Chinese and English are no longer pinned on top for
  everyone.
- Settings - Captions - Timing shows only the chosen timing's own
  settings, in seconds, each with what it trades: Quick preview says when
  its dim lines come, and Live updates says when the longest wait for
  text makes it update sooner than the interval you chose.

- The first screen asks only that you agree to the tester agreement; it
  no longer asks you to state your age (the agreement and the privacy
  notice say who Polyglotic is for).
- After you send a report or a suggestion, a notification says when it
  has reached us - or that it's saved to send later - so you see it in a
  game or a call too. Not while Polyglotic's Home is in front, which says
  it already.
- Moving the mouse across a caption window's words is lighter: only the
  captions it passes over are redrawn, and a lookup card following the
  mouse looks up the word it stops on, not every word on the way.
- The Panel | Strip choice is gone from the caption windows' settings: every
  window is a panel the size you set, and one you had as a strip opens as
  a panel.
- Settings is bigger and has three sections at its top: Captions, Learning
  and App. Captions holds every caption window's settings in one place -
  the look, word links, timing, fading and names and slang - each with a
  line saying what it does. A caption window's "All caption settings…"
  opens it; the small Look window is gone, and so are Home's Languages
  and Timing panels (the window's settings keep a Timing shortcut).
  Resetting the look no longer moves your caption windows: Home's Reset
  positions does that.
- A caption window's settings show Timing on one line, the timing now on
  a button that opens the three choices; all of it is in Settings.
- Settings' "Ask me the first-run questions again" is split where each
  answer belongs: change your level on Learning, and what you share on
  Account.
- Steady is the default timing again: each sentence appears once,
  finished and translated. A timing you chose stays; Help's "When do
  captions appear?" says what each does.
- In Steady and Quick preview, someone talking on without a pause is
  captioned in shorter pieces, so the next caption comes sooner.
- When Polyglotic's server can't be reached, Home, the caption windows and
  the tray say why - no internet, our server down or restarting, a
  firewall or proxy, the PC's clock - whose problem it is, and what to do,
  instead of just "Reconnecting".
- Signing in while Polyglotic's server can't be reached says whose problem
  it is, instead of always asking you to check your internet.
- Captions no longer fade away when nobody is talking, unless you choose
  a time in Settings - Captions - Fade after quiet. A time you chose
  before is kept.
- The caption font Polyglotic picks is now called "Polyglotic (Default)".
- Quick preview's dim first lines come with their translation too, until
  the finished caption replaces them.
- Names and slang shows examples you'll recognise (rizz, yyds, 鸡你太美, a
  streamer's or a game's name), and takes Chinese commas and 、 between them.
- "Looks wrong?" now says what it does and what it sends before it sends
  anything: choose Send report, or Cancel.
- Steady, Quick preview and Live updates each say what they do when you
  point at them, and so do a caption window's settings, All caption
  settings… and Open transcript.
- A locked caption window says how to unlock it (Ctrl+Alt+L) when you lock
  it, then shows the keys faintly in its corner.
- A caption window's settings no longer have Position: drag the window
  where you want it, and it stays there.
- Word links have a button of their own on each caption window. The text
  size buttons (A- / A+) moved into the window's settings. While the
  original is hidden, the button is dimmed and says why: word links need
  what was said shown.
- The newest caption stands out: as it comes in, the captions before it
  slide up and step back a little, and it rises into place from below -
  quicker when people talk quicker - so you can tell what just came in
  from the corner of your eye. Nothing moves under the mouse; with
  Windows' animation effects off, it simply appears. With Windows' high
  contrast, nothing steps back. While you've scrolled back to read, every
  caption is at full brightness.
- Word links' underlines sit below letters like g and y instead of through
  them, and you can make them thinner or thicker and closer or further in
  Settings - Captions - Word links.
- Words: Your words shows its first 8 words, then Show all - or search for
  the one you want - instead of every word you've met.
- Words: Saved words shows its first 8 words, then Show all, instead of
  every word you've saved.
- Words: Words you keep hearing shows the top 5, and Show more adds 10 at
  a time.
- Words: Export for Anki links to How to import into Anki, on our
  website's help.
- The first run has Back on every screen after the first, keeping what
  you entered, and asks for your code before the main window opens.
- Save transcript as... and Export for Anki open in your Documents folder,
  or where you saved last - never in the app's own folder, which updates
  replace.
- Quick preview keeps its dim line up to date while someone talks on,
  instead of one first guess and then nothing until they pause.
- Steady no longer goes quiet through a long stretch of talk: once someone
  has talked for 3 seconds, a dim, translated line shows what they've
  said so far, until the finished caption takes its place. Quick preview
  and Live updates never leave you longer than that without text either.

### Fixed

- Settings - App - Hotkeys wrote Ctrl+Alt+L, P and H in English while the
  rest of the app wrote them in its own language (Strg+Alt+L in German).
  They're written the same way everywhere now.
- Report a problem on a laptop's short screen, at a larger text size or in a
  longer language (German, Japanese), was squeezed to fit: the line for what
  happened covered the first part and the last lines were cut off. Now the
  window fits the screen and what's between the title and Send scrolls.
- Moving the mouse over a caption window while a caption was sliding in
  stopped it halfway, its last lines cut off at the bottom for as long as
  the mouse stayed. The caption now settles in place at once, whole.
- Dictation with the server out of reach said "Working…" for 10 seconds
  before giving up. It now says "Not connected to the server" at once,
  and nothing you said is sent later.
- With "Caption my own speech" on, what you dictated also showed as a
  "You" line, and its minutes counted twice. While the dictation key is
  held, your mic now goes to dictation only; a line you were saying as
  you pressed it is finished with what you said before.
- After choosing another language to learn - English instead of Chinese,
  say - Words went on showing the other language's words without saying
  so, until Polyglotic started again. It now says whose words they are
  and that the new language is used from the next start.
- Fast speech with no pauses (a quick-talking video, say) was cut into
  captions every 6 seconds wherever the cut fell: mid-word, each piece
  ending in a full stop, often with the last word or two repeated at the
  start of the next. It's now cut at the quietest moment just before,
  with no words repeated and no full stop where the speech goes on.
- On some PCs (one seen on Windows 10), Polyglotic froze for about a
  second as Home opened, while it asked Windows which apps play sound.
  It now asks in the background.
- When Windows' text size changes while Polyglotic is open, a caption
  window's or transcript's notice ("Paused", "Reconnecting...") and Back
  to live, the "Looks wrong?" card and the pages of the main window all
  grow with it - nothing is cut off until a restart.

- With "Caption my own speech" on, sound from your speakers that your mic
  picks up is caught more often and not shown as yours - when it reaches
  the mic late, as from Bluetooth speakers, or while Windows' volume is
  low and the speakers are turned up.
- Signing in, updates and reports could be refused before they reached
  our server ("Something on this network is in the way"). Fixed on our
  side for every version, and the app now says who it is.
- Exporting your words for Anki no longer freezes the app while the file
  is written, and it says where the file went.
- Dragging a slider in Settings no longer floods the server with your
  settings, which could make it turn away the speech sent at the same
  moment. The server now gets a change once you let go, and only one it
  needs.
- Dragging the panel's slider in Settings > Captions no longer holds up
  the app: the caption windows follow it as you drag, and it's saved
  once you let go.
- Your level's screen, learning Chinese, opens faster and no longer
  flashes its drop-down as a window of its own first.
- Polyglotic open on too many of your PCs, or too many failed sign-ins
  from your network, say so - they read "Reconnecting", like a dropped
  connection.
- Polyglotic's windows show its own icon, in their title bars and in
  Alt-Tab, instead of Windows' plain one.
- A code from a Plus email whose subscription was cancelled before it was
  used says so, and how to get Plus, instead of "This code doesn't work".
- A new caption's last line - often its translation - no longer stays
  cut off at the bottom of the caption window after sliding in.
- A caption on its way when you changed what's captioned is no longer
  lost: it's shown once the new captioning starts.
- A caption window's panel stays the size you set: it no longer grows and
  shrinks with the text as live captions come, and a joined window's
  quiet column shows its panel beside the others.
- After locking and unlocking Windows, moving the mouse over a caption
  window shows its top bar again.
- A caption window Windows minimises - "Show desktop", for one - comes
  straight back instead of staying gone until you restart Polyglotic.
- A caption window's top bar - its icons and its app's name - is readable
  on every colour preset and any panel colour you pick: dark on Paper's
  cream, where it was white.
- The first run's Your data screen no longer flashes a scroll bar over
  its text as it opens.
- Your invite code now works again on the PC you used it on, as often as
  you need: after signing out, or if Polyglotic ever asks you to sign in
  again, type the same code. Another PC still needs its own code.

## 0.1.0 - 2026-11-12

The first test version, for friends: unsigned, on the alpha channel, with
captions from a server on our own PC. Thank you for trying it - tell us
what breaks with Report a problem.

### New

- Captions of what you hear, with a translation underneath: pick up to
  three apps, each in a caption window of its own, or everything the PC
  plays.
- Your own speech captioned too, in the window you choose ("Show my speech
  here").
- A translation language for each window, or the original only.
- Three caption timings: Steady (each sentence appears once, finished),
  Quick preview and Live updates.
- Caption windows as a panel or a strip, moved and resized from any edge,
  with bigger or smaller text, a lock, and a fade - they never take the
  focus from your game.
- A transcript for each app: search it, copy it, or save it as text, SRT
  or CSV.
- Look up any word in a caption: Chinese (CC-CEDICT, with HSK 3.0 levels)
  and English (ECDICT) dictionaries on your PC, with how common each word
  is.
- Mark words as learning, known or ignored; words you don't know yet are
  marked in finished captions.
- Words: your saved words, the words you keep hearing, and how much of
  what you hear you already know.
- Export for Anki: a ready-made deck file (.apkg) or a CSV, each card with
  the sentence you heard the word in.
- "Looks wrong?" on a finished line asks the server to check it again with
  its best models.
- Report a problem and Suggest something, from Help.
- The interface in English, Simplified Chinese and Traditional Chinese
  (the Chinese wording is still being reviewed).
- Three looks - Margin, Glaze and Signal - in light and dark; text follows
  Windows' text size.
- Sign in with your invite code. Usage statistics are sent only if you
  agree, and never what's said.
- Updates download quietly and apply the next time Polyglotic starts.
