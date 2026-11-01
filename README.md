# Callout

Live English subtitles for your teammates' voice chat in Counter-Strike 2.

Callout listens to the game's audio, works out which language each sentence is
in, and shows an English translation in a small overlay on top of the game.
Russian, Ukrainian, Polish, Turkish, German, French, Spanish, Portuguese,
Italian, Chinese, Japanese, Korean and Arabic are on by default; about 30
languages can be switched on. Everything runs on your own PC.

![Captions over the game](docs/overlay.png)

![The Callout window](docs/app.png)

## Download

1. Go to [Releases](https://github.com/fgmrkt/callout/releases) and download
   `Callout-vX.Y.Z-win64.zip`.
2. Unzip it to a folder you own (for example Documents) and run `Callout.exe`.
3. Windows may show a SmartScreen warning because the app is not code-signed.
   Click **More info**, then **Run anyway**.

You only download Callout once. Every time it starts, it checks this
repository for a newer release, downloads it, swaps its own files and
restarts. Your settings and downloaded models are kept. To update by hand
instead, turn off **About → Update automatically when Callout starts** and use
**Check for updates**.

## First start

1. In Counter-Strike 2, set **Settings → Video → Display Mode** to
   **Fullscreen Windowed**. In plain Fullscreen the game hides every other
   window, including the overlay.
2. Click **Start listening**. The first time, Callout downloads what it needs:
   - **GPU support** (NVIDIA cards only, about 1.2 GB): NVIDIA's cuBLAS and
     cuDNN libraries, straight from NVIDIA's packages on PyPI.
   - **The speech model** (Whisper large-v3, about 3.1 GB) from Hugging Face.
3. Open **Overlay → Move overlay**, drag the box where you want captions, and
   press **Done**. Captions line up left, centre or right depending on where
   you put it.
4. Join a match. The signal meter at the top turns gold when Callout hears
   someone talking.

## Requirements

- Windows 10 (version 2004 or newer) or Windows 11
- Recommended: an NVIDIA GeForce RTX card with 4 GB of free VRAM. The large
  model uses about 3–4 GB and a few hundred milliseconds of GPU time per
  sentence, which games don't notice on modern cards.
- RTX 50-series cards need NVIDIA driver 570 or newer.
- Without an NVIDIA GPU, Callout runs on the CPU. Pick the **Small** model in
  **Audio & model** for real-time speed.

## How it works

```
cs2.exe audio ──► voice detector ──► Whisper ──────────────► overlay
 (game only)       (Silero VAD)      language ID +            + live log
                   cuts sentences,   translation to English
                   skips gunfire
```

- **Audio**: Windows' per-process loopback captures only `cs2.exe`, so music
  or YouTube in the background is not picked up. If the game is not running
  (or you choose *Everything I hear*), it captures your whole output device,
  which also covers Discord.
- **Voice detection**: Silero VAD cuts the stream into sentences and skips most
  gunshots, footsteps and other game sounds before they reach Whisper.
- **Translation**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  runs OpenAI's Whisper model. It identifies the language, then translates
  straight into English. A short list of Counter-Strike terms helps it spell
  callouts. Known Whisper hallucinations ("Thanks for watching", subtitle
  credits) are filtered out.

## Reading the original words

Under each translation Callout can show what was actually said. Under
**Languages → Write the original words in** you choose their own alphabet
(Привет, 你好), Latin letters (Privet, nǐ hǎo) or both. Latin letters cover
Cyrillic, Chinese pinyin with tones, Korean, Arabic, Greek, Hebrew, Thai and
Hindi. Japanese kana become romaji; kanji stay as they are.

## Privacy and anti-cheat

- Audio never leaves your computer, and nothing you hear is saved to disk.
  The log file only contains technical messages. The only network traffic is
  the one-time downloads above and the update check against GitHub.
- Callout is a separate program. It only reads the sound the game plays; it
  never touches the game's memory or files and doesn't inject anything, so it
  is safe with VAC.

## Limitations

- In-game voice chat is one mixed sound, so Callout can't tell which teammate
  said what.
- Translations appear about a second after someone stops talking.
- Loud gunfights, bad microphones and heavy slang lower accuracy.

## Troubleshooting

| Problem | Try this |
| --- | --- |
| Overlay doesn't show in game | Use Fullscreen Windowed. Check **Show captions over the game** is ticked. |
| Meter moves, but no captions | Make sure the language is ticked under **Languages**. English is ignored unless you turn it on. |
| Meter doesn't move | Turn up voice chat volume in CS2. Or set **What to listen to** to *Everything I hear*. |
| "Could not load the speech model" on an NVIDIA GPU | Update your NVIDIA driver, or set **Run on** to CPU. |
| Something else | Logs are in `%LOCALAPPDATA%\Callout\logs`. Open an issue with the log attached. |

All settings, models and the GPU runtime live in `%LOCALAPPDATA%\Callout`.
Delete that folder to reset Callout completely.

## Run from source

Requires Python 3.12 on Windows.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Run the tests with `pip install -r requirements-dev.txt` and `python -m pytest`.
Set `CALLOUT_DEBUG=1` to log every caption while testing.

## Building and releasing

GitHub Actions builds the Windows app on every push (see the **Actions** tab
for a downloadable zip). To publish a release, which every installed copy
then picks up on its next start:

1. Bump `__version__` in `callout/__init__.py` (for example to `0.1.2`) and commit.
2. Tag and push:

   ```bash
   git tag v0.1.2
   git push origin main v0.1.2
   ```

The workflow checks the tag matches `__version__`, runs the tests, builds
`Callout.exe` with PyInstaller, checks the build with `--self-test`, tests the
self-updater, and attaches the zip to a new release.

To build locally: `pip install -r requirements-dev.txt` and
`pyinstaller callout.spec --noconfirm`. The app ends up in `dist\Callout`.

## Credits

- [Whisper](https://github.com/openai/whisper) by OpenAI, run with
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and
  [CTranslate2](https://github.com/OpenNMT/CTranslate2)
- [Silero VAD](https://github.com/snakers4/silero-vad)
- [ProcTap](https://github.com/m96-chan/ProcTap) for per-process audio capture,
  [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) for output loopback
- [Barlow](https://github.com/jpt/barlow) typeface (SIL Open Font License)
- Built with [PySide6](https://doc.qt.io/qtforpython-6/)

Licensed under the MIT License.
