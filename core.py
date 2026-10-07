"""Local HLS inspection and lossless capture. No web service or telemetry."""
import os, re, sys, time, json, shutil, subprocess, threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urljoin
from datetime import datetime
import m3u8
from curl_cffi import requests

VERSION = '0.1.0'
ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://kick.com/'}
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
DIAGNOSTICS = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'StinkSNIFFER' / 'diagnostics'
INPUT_RETRIES = ['-rw_timeout', '15000000', '-reconnect', '1', '-reconnect_streamed', '1',
    '-reconnect_on_network_error', '1', '-reconnect_on_http_error', '408,429,500,502,503,504',
    '-reconnect_delay_max', '8', '-reconnect_max_retries', '4', '-reconnect_delay_total_max', '30',
    '-respect_retry_after', '0', '-seg_max_retry', '3', '-max_reload', '3']

@dataclass
class CaptureResult:
    path: str
    state: str
    details: str
    log: str

def estimate_bytes(source, variant):
    # EXT-X-STREAM-INF BANDWIDTH is the aggregate peak video + associated audio bitrate.
    # Counting the audio a second time would inflate this estimate.
    bitrate = variant.bandwidth
    if not bitrate:
        rates = []
        for url in (variant.url, variant.audio):
            if not url: continue
            p = playlist(url)
            media_duration(p)
            if not p.segments: raise ValueError('No segments available for the size estimate.')
            indices = sorted(set([0, len(p.segments)//2, len(p.segments)-1]))
            samples = []
            for index in indices:
                segment = p.segments[index]
                if segment.duration <= 0: continue
                if segment.byterange:
                    size = int(segment.byterange.split('@')[0])
                else:
                    r = requests.head(segment.absolute_uri, headers=HEADERS, impersonate='chrome', timeout=15, allow_redirects=True)
                    r.raise_for_status()
                    size = int(r.headers.get('content-length', '0'))
                if size: samples.append(size * 8 / segment.duration)
            if not samples: raise ValueError('Size cannot be estimated safely: no rendition bitrate or segment sizes were supplied.')
            rates.append(max(samples) * 1.2)
        bitrate = sum(rates)
    if not source.duration or bitrate <= 0:
        raise ValueError('Size cannot be estimated without bitrate and source duration.')
    return int(bitrate * source.duration / 8)

def storage_check(folder, estimated):
    path = Path(folder)
    while not path.exists() and path != path.parent: path = path.parent
    free = shutil.disk_usage(path).free
    required = estimated + max(int(estimated * .1), 1024**3)
    return {'estimated': estimated, 'free': free, 'required': required, 'sufficient': free >= required}

def classify_completion(code, usable, log, output_duration, expected_duration):
    if not usable: return 'Failed'
    text = '\n'.join(log).lower()
    warnings = any(word in text for word in ('i/o error', 'input/output error', 'error during demuxing',
        'failed to open segment', 'failed to reload', 'http error', 'connection reset', 'connection timed out',
        'will reconnect', 'retrying', 'corrupt', 'packet corrupt', 'error when loading', 'end of file', 'error reading'))
    short = expected_duration and output_duration < expected_duration - max(3, expected_duration*.005)
    fatal_output = any(word in text for word in ('no space left', 'error writing', 'error muxing', 'error closing', 'error opening output', 'permission denied'))
    if fatal_output or (code != 0 and not warnings): return 'Failed'
    return 'Success with source/read warnings' if warnings or short else 'Success'

def binary(name):
    local = ROOT / 'bin' / (name + '.exe')
    return str(local) if local.exists() else shutil.which(name)

def fetch(url):
    if urlparse(url).scheme not in ('https', 'http'):
        raise ValueError('Only HTTP/HTTPS sources are supported.')
    r = requests.get(url, headers=HEADERS, impersonate='chrome', timeout=25)
    r.raise_for_status()
    return r

@dataclass
class Variant:
    height: int
    url: str
    audio: str = ''
    bandwidth: int = 0

@dataclass
class Source:
    title: str
    streamer: str
    date: str
    duration: float
    variants: list
    thumbnail: bytes = b''
    master: str = ''

def playlist(url):
    r = fetch(url)
    if not r.text.lstrip().startswith('#EXTM3U'):
        raise ValueError('The source did not return an M3U playlist.')
    p = m3u8.loads(r.text, uri=str(r.url))
    return p

def media_duration(p):
    if not p.is_endlist:
        raise ValueError('This is a live or unfinished playlist. Use a completed VOD for a finite export.')
    return sum(s.duration for s in p.segments)

def probe(url):
    ffprobe = binary('ffprobe')
    if not ffprobe:
        raise ValueError('FFprobe is needed to identify this media playlist.')
    r = subprocess.run([ffprobe, '-v', 'error', '-headers', 'Referer: https://kick.com/\r\n',
                        '-show_streams', '-of', 'json', url], capture_output=True, timeout=35, creationflags=FLAGS)
    if r.returncode:
        raise ValueError('Unable to identify the media rendition.')
    return next((s.get('height', 0) for s in json.loads(r.stdout).get('streams', []) if s.get('codec_type') == 'video'), 0)

def inspect(url, metadata=None):
    metadata = metadata or {}
    p = playlist(url)
    variants = []
    if p.is_variant:
        for item in p.playlists:
            info = item.stream_info
            if not info.resolution:
                continue
            audio = next((m.absolute_uri for m in p.media if m.type == 'AUDIO' and m.group_id == info.audio and m.uri and m.default == 'YES'), '')
            if info.audio and not audio:
                audio = next((m.absolute_uri for m in p.media if m.type == 'AUDIO' and m.group_id == info.audio and m.uri), '')
            variants.append(Variant(info.resolution[1], item.absolute_uri, audio, info.bandwidth or 0))
    elif p.segments:
        variants.append(Variant(probe(url), url))
    else:
        # A plain M3U may contain one playlist URL. Never concatenate unrelated videos.
        entries = [line.strip() for line in fetch(url).text.splitlines() if line.strip() and not line.startswith('#')]
        if len(entries) == 1:
            return inspect(urljoin(url, entries[0]), metadata)
        raise ValueError('Use a single HLS master/media playlist, not a list of unrelated streams.')
    if not variants:
        raise ValueError('No video renditions found.')
    selected = max(variants, key=lambda v: (v.height, v.bandwidth))
    duration = media_duration(playlist(selected.url))
    thumb = b''
    if metadata.get('thumbnail'):
        try:
            thumb = fetch(metadata['thumbnail']).content
        except Exception:
            pass
    if not thumb and binary('ffmpeg'):
        try:
            r = subprocess.run([binary('ffmpeg'), '-v', 'error', '-headers', 'Referer: https://kick.com/\r\n',
                '-i', selected.url, '-frames:v', '1', '-vf', 'scale=640:-1', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'],
                capture_output=True, timeout=25, creationflags=FLAGS)
            if r.returncode == 0:
                thumb = r.stdout
        except subprocess.TimeoutExpired:
            pass
    return Source(metadata.get('title') or 'Direct HLS capture', metadata.get('streamer') or urlparse(url).hostname,
        metadata.get('date') or 'date unavailable', duration, variants, thumb, url)

def resolve(value):
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme in ('https', 'http') and parsed.hostname not in ('kick.com', 'www.kick.com'):
        return inspect(value)
    slug = parsed.path.strip('/').split('/')[0] if parsed.hostname in ('kick.com', 'www.kick.com') else value.lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', slug):
        raise ValueError('Enter a Kick username or an HTTP/HTTPS M3U8 URL.')
    listing = fetch(f'https://kick.com/api/v2/channels/{slug}/videos').json()
    entries = listing if isinstance(listing, list) else listing.get('data', listing.get('videos', []))
    if not isinstance(entries, list) or not entries:
        raise ValueError('No accessible VODs found for this channel.')
    entries.sort(key=lambda x: str(x.get('created_at', '')), reverse=True)
    failures = []
    for entry in entries[:20]:
        try:
            video = entry.get('video') or entry
            uid = video.get('uuid') or entry.get('uuid')
            detail = entry if entry.get('source') else (fetch(f'https://kick.com/api/v1/video/{uid}').json() if uid else entry)
            stream = detail.get('livestream') or entry
            if stream.get('is_live'):
                continue
            url = detail.get('source') or video.get('source')
            if not url:
                continue
            thumbnail = stream.get('thumbnail') or entry.get('thumbnail')
            if isinstance(thumbnail, dict):
                thumbnail = thumbnail.get('url') or thumbnail.get('src')
            return inspect(url, {'title': stream.get('session_title') or entry.get('session_title'), 'streamer': slug,
                'date': str(detail.get('created_at') or entry.get('created_at') or '')[:10], 'thumbnail': thumbnail})
        except Exception as e:
            failures.append(str(e))
    raise ValueError('No completed accessible VOD could be resolved. Try a direct M3U8 URL. ' + (failures[-1] if failures else ''))

def filename(source, variant):
    name = f'{source.streamer}_{source.date}_{source.title}_{variant.height}p'
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:160]
    if name.split('.')[0].upper() in ('CON', 'PRN', 'AUX', 'NUL'):
        name = '_' + name
    return name + '.mp4'

def capture(source, variant, folder, progress, cancel):
    ffmpeg = binary('ffmpeg')
    if not ffmpeg:
        raise ValueError('FFmpeg was not found. Put ffmpeg.exe in the bin folder.')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    storage = storage_check(folder, estimate_bytes(source, variant))
    if not storage['sufficient']:
        raise ValueError(f"INSUFFICIENT DISK SPACE. Need ~{storage['required']/1024**3:.1f} GB; available {storage['free']/1024**3:.1f} GB.")
    destination = folder / filename(source, variant)
    base = destination.stem
    index = 1
    while destination.exists() or destination.with_suffix('.partial.mp4').exists():
        destination = folder / f'{base}_{index}.mp4'
        index += 1
    partial = destination.with_suffix('.partial.mp4')
    log = []
    DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    log_path = DIAGNOSTICS / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + destination.stem + '.log')
    logfile = log_path.open('w', encoding='utf-8')
    logfile.write(f'StinkSNIFFER {VERSION}\nRendition: {variant.height}p\nOutput: {destination}\n')
    command = [ffmpeg, '-hide_banner', '-nostdin', '-n', '-loglevel', 'warning', *INPUT_RETRIES,
               '-headers', 'Referer: https://kick.com/\r\n', '-i', variant.url]
    if variant.audio:
        command += [*INPUT_RETRIES, '-headers', 'Referer: https://kick.com/\r\n', '-i', variant.audio, '-map', '0:v:0', '-map', '1:a:0']
    else:
        command += ['-map', '0:v:0', '-map', '0:a:0?']
    command += ['-c', 'copy', '-progress', 'pipe:1', '-stats_period', '0.5', str(partial)]
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', creationflags=FLAGS)
    except Exception:
        logfile.close(); raise
    def errors():
        for line in proc.stderr:
            # Remove signed URL query strings from diagnostic logs.
            line = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[redacted]', line)
            logfile.write(line); logfile.flush()
            log.append(line.strip())
            if len(log) > 40:
                log.pop(0)
    reader = threading.Thread(target=errors, daemon=True)
    reader.start()
    def stop():
        while proc.poll() is None:
            if cancel.wait(.2):
                proc.terminate()
                try: proc.wait(5)
                except subprocess.TimeoutExpired: proc.kill()
                return
    watcher = threading.Thread(target=stop, daemon=True)
    watcher.start()
    started = time.monotonic()
    state = {}
    seconds = 0
    try:
        for line in proc.stdout:
            key, _, val = line.strip().partition('=')
            state[key] = val
            if key == 'progress':
                seconds = max(0, int(state.get('out_time_us', '0')) / 1_000_000)
                size = partial.stat().st_size if partial.exists() else 0
                progress({'seconds': seconds, 'size': size, 'speed': state.get('speed', '—'), 'elapsed': time.monotonic() - started})
        code = proc.wait()
        reader.join(2)
        if cancel.is_set():
            raise ValueError('Capture cancelled. Partial file removed.')
        if not partial.exists() or partial.stat().st_size == 0:
            raise ValueError('FFmpeg produced an empty file.')
        check = subprocess.run([binary('ffprobe'), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(partial)],
            capture_output=True, timeout=45, creationflags=FLAGS)
        data = json.loads(check.stdout) if check.returncode == 0 else {}
        duration = float(data.get('format', {}).get('duration', 0))
        usable = duration > 0 and any(s.get('codec_type') == 'video' for s in data.get('streams', []))
        # Decode a short frame from the local MP4, without transcoding the export.
        validation = subprocess.run([ffmpeg, '-v', 'error', '-i', str(partial), '-frames:v', '1', '-f', 'null', '-'],
            capture_output=True, timeout=45, creationflags=FLAGS)
        usable = usable and validation.returncode == 0
        logfile.flush()
        state_name = classify_completion(code, usable, [log_path.read_text(encoding='utf-8')], duration, source.duration)
        if state_name == 'Failed': raise ValueError('Capture failed. See Options → Diagnostics. ' + ' / '.join(log[-3:]))
        partial.rename(destination)
        details = f'Saved {clock(duration)} of {clock(source.duration)}. Some source segments may be missing.' if state_name != 'Success' else ''
        logfile.write(f'\nState: {state_name}\nDuration: {duration} / {source.duration}\n')
        return CaptureResult(str(destination), state_name, details, str(log_path))
    except Exception as e:
        logfile.write(f'\nState: Failed\n{e}\n')
        raise
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if partial.exists():
            partial.unlink()
        proc.stdout.close(); proc.stderr.close()
        logfile.close()

def latest_release(repo):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
        raise ValueError('Set a GitHub release repository as owner/name in Options.')
    data = fetch(f'https://api.github.com/repos/{repo}/releases/latest').json()
    from packaging.version import Version
    if Version(data['tag_name'].lstrip('v')) > Version(VERSION):
        return data
    return None

def vlc_path():
    candidate = shutil.which('vlc')
    if candidate: return candidate
    for key in ('ProgramFiles', 'ProgramFiles(x86)'):
        p = Path(os.environ.get(key, 'C:/Program Files')) / 'VideoLAN/VLC/vlc.exe'
        if p.exists(): return str(p)
    return ''

def clock(seconds):
    seconds = int(seconds or 0)
    return f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}'
