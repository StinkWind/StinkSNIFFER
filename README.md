# StinkSNIFFER v0.4.0

Run `StinkSNIFFER.exe` in the portable folder. Keep its `_internal` folder beside it. Python and FFmpeg installation are not required for the packaged build.

Enter a Kick username or a direct HTTP/HTTPS HLS master/media playlist. Source inspection reveals the preview and quality choices. Choose a quality to estimate size and check the export drive before SAVE appears. Native 480p/720p/1080p variants are enabled only when available. Other native resolutions appear if none of these exists.

Exports default to Windows' Videos folder under `StinkSNIFFER`. Options changes the folder persistently, opens diagnostics, and configures/checks GitHub Releases. The release dialog displays notes and opens the release page only after you click its download button. No automatic executable replacement.

## Interface / Sniffy

- Taller window with storage, SAVE and progress outside the scrolling preview. SNIFF and the × clear-source button sit inside the source bar. Clear retains history/preferences and is disabled during capture.
- The main transparency slider has a pulsing pixel eye: 0–100%, default 0 (fully opaque). The charcoal shell and looping skull GIF fade together. Controls, text, and Sniffy remain fully opaque. User-selected transparency is remembered.
- Sniffy is an animated pixel skull with a transparent matte. His compact first-launch speech bubble explains the capture flow, with occasional paperclip references. GOT IT remembers dismissal; Options → Show tips / Hide Sniffy restores or hides him.
- Sniffy has reserved space above storage details. Speech persists; when export is ready, ten idle seconds trigger a small bounce and another non-repeating export remark. Capture/error messages remain relevant.
- SAVE starts export immediately while GLITCH LAUGH's extracted audio plays, followed by the supplied music. Startup, shutdown, speech and error cues play softly. Options → Mute all sounds and the progress MUTE/UNMUTE share one remembered setting. Completion, errors and cancellation stop capture audio.
- Recent streams stores five inspected sources by title, re-inspects selected links, and explains their typical ~30-day expiry. Each launch starts with an empty source and preview.
- Filenames: `💀StreamerName_YYYY-MM-DD💀.mp4`, using the VOD live date. Duplicates add `_2`, `_3`, etc. before the closing skull. If direct HLS links lack streamer/date metadata, enter the actual name/date before SAVE becomes available.
- GitHub update checks default to `StinkWind/StinkSNIFFER` on launch; release notes and a user-confirmed release-page download are supported.

## Reliability

- Stream copy/remux, no export transcoding.
- Each HTTP connection: up to four retries, maximum 30 seconds reconnect delay; transient 408/429/500/502/503/504 responses and network connection errors. Normal EOF is not retried.
- HLS segment retries: three. Input read timeout: 15 seconds. No whole-job restart loop.
- Completion states: Success, Success with source/read warnings, Failed. Finalized MP4s are checked with FFprobe and a decoded frame. Read errors, retries, corrupt-packet reports, and short output trigger the warning state; usable MP4s are retained, including nonzero exits attributable to source reads. Output/muxing/disk errors still fail. This is a usability check, not a full-file integrity guarantee.
- Failed/cancelled incomplete files are removed. Existing exports are never overwritten.
- Full FFmpeg warning/error details in `%LOCALAPPDATA%\StinkSNIFFER\diagnostics`; signed URL query strings are redacted.
- Estimated bytes = aggregate rendition bitrate (bits/s) × duration / 8. Master BANDWIDTH already includes associated audio. Where missing, three segment sizes are sampled, with separate audio included and an additional conservative allowance. If no safe estimate exists, SAVE remains unavailable.
- Required free space: estimate + max(10%, 1 GiB), checked again at export start. Sizes are displayed using binary GB units. Estimates cannot guarantee exact size for variable bitrate sources.
- Completed VODs only; live/unfinished playlists are rejected. Direct URLs do not inherently contain streamer/title/date metadata; unknown values are labelled accordingly.

## Source / rebuilding

`app.py`, `core.py`, `requirements.txt`, `build.ps1`, `assets`, and `bin` contain the standalone project. Install Python 3.14, then run `build.ps1`. FFmpeg/FFprobe are included from the locally installed Gyan FFmpeg build. FFmpeg redistribution terms and corresponding source: https://www.gyan.dev/ffmpeg/builds/ and https://ffmpeg.org/legal.html. Cascadia Mono is the exact GlassChat font, converted from its WOFF2 asset, under the SIL Open Font License: https://github.com/microsoft/cascadia-code.

The source repository excludes the user-supplied media and FFmpeg binaries. For a rebuild, supply `assets/media/watermark.gif`, `capture-music.mp3`, `sniffy.gif`, `laugh.wav`, `speech.wav`, `error.wav`, `startup.wav`, `shutdown.wav` in the same media folder, and `bin/ffmpeg.exe` / `bin/ffprobe.exe`. The portable release includes them. Windows 10/11 is required; the build script avoids a conflicting Conda ICU DLL.

No telemetry, hosted backend, or OBELISK changes. Network traffic is limited to the requested source, Kick resolution/thumbnail requests, and configured GitHub update checks.
