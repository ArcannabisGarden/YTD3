"""Metadata, extraction, conversion, and tagging without desktop dependencies."""
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
import glob
import os
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


@dataclass
class Track:
    url: str
    video_id: str
    title: str
    artist: str
    album: str = ''
    albumartist: str = ''
    track: str = ''
    year: str = ''
    genre: str = ''
    artwork: str = ''


def clean_title(title):
    label = r'(?:official(?: music)? (?:video|audio)|official|lyrics?|lyric video|music video|audio|video|visualizer)'
    title = re.sub(r'\s*[\[(]\s*' + label + r'\s*[\])]\s*', ' ', title, flags=re.I)
    title = re.sub(r'\s*[-–—|]\s*' + label + r'\s*$', '', title, flags=re.I)
    return re.sub(r'\s+', ' ', title).strip()


def guess_metadata(title, author):
    artist = re.sub(r'\s*-\s*Topic$', '', author, flags=re.I).strip()
    title = clean_title(title)
    pieces = re.split(r'\s+[-–—]\s+', title, maxsplit=1)
    if len(pieces) == 2 and all(pieces):
        artist, title = pieces
    return title, artist


def validate_url(url):
    parsed = urlparse(url.strip())
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in (
        'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'
    ) or parsed.username or parsed.password:
        raise ValueError('Enter a valid youtube.com or youtu.be URL.')
    return parsed


def is_album_playlist(url):
    parsed = validate_url(url)
    return parse_qs(parsed.query).get('list', [''])[0].startswith(('OLAK5uy_', 'OL'))


class DownloadFailure(RuntimeError):
    def __init__(self, message, stop_batch=False, video_only=False, needs_sign_in=False):
        super().__init__(message)
        self.stop_batch = stop_batch
        self.video_only = video_only
        self.needs_sign_in = needs_sign_in


def format_error(error):
    # Preserve the underlying reason while removing signed media URLs and ANSI.
    text = re.sub(r'\x1b\[[0-9;]*m', '', str(error))
    if any(word in text.lower() for word in ('cookies file', 'cookie file', 'cookiejar', 'invalid cookie')):
        return 'Could not read the session file. Select a valid Netscape-format YouTube cookies.txt file, or clear it.'
    text = re.sub(r'https?://[^\s\]\)]+', '[request URL]', text)
    return text[-1800:] or type(error).__name__


def classify_download_error(error):
    text = format_error(error)
    lowered = str(error).lower()
    # Age verification applies to this video, not the whole playlist.
    if any(word in lowered for word in ('confirm your age', 'age-restricted', 'age restricted', 'age restriction')):
        return DownloadFailure(
            'This song needs YouTube age verification. Check that it plays in your signed-in browser. '
            'To retry it in the app, load a local cookies.txt session from that account, then retry unfinished songs. '
            'Other songs in the playlist will continue.\nDetails: ' + text,
            video_only=True, needs_sign_in=True,
        )
    if any(word in lowered for word in (
        'not a bot', 'sign in', 'login required', 'cookies', 'http error 403', 'http error 429',
        'potoken', 'po token', 'sabr', 'maximum', 'retry', 'retries', 'timed out', 'timeout',
        'unable to download', 'connection', 'certificate', 'network is unreachable',
        'no supported javascript', 'requested format is not available',
    )):
        return DownloadFailure(
            'Download stopped: ' + text + '\n'
            'If YouTube requests sign-in, use a local YouTube cookies.txt file in the session picker. '
            'For network or stream errors, retry unfinished songs later or use a newer app build.',
            stop_batch=True,
        )
    return DownloadFailure(text)


class QuietLogger:
    def __init__(self, report):
        self.report = report

    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        self.report('warning', format_error(message))

    def error(self, message):
        # yt-dlp raises DownloadError with this reason; report it once there.
        pass


def node_path():
    from nodejs_wheel import executable
    root = Path(executable.ROOT_DIR)
    return str(root / 'node.exe' if os.name == 'nt' else root / 'bin' / 'node')


def extractor_options(workdir, cookies_file=None, report=lambda *_: None):
    options = {
        'quiet': True, 'no_warnings': False, 'no_color': True,
        'logger': QuietLogger(report), 'socket_timeout': 15,
        'retries': 2, 'fragment_retries': 2, 'extractor_retries': 1,
        'file_access_retries': 1, 'concurrent_fragment_downloads': 1,
        'cachedir': False, 'js_runtimes': {'node': {'path': node_path()}},
        'ffmpeg_location': ffmpeg_path(),
    }
    if cookies_file:
        # Work on a private temporary copy; yt-dlp can update its cookie jar.
        source = Path(cookies_file).resolve()
        if not source.is_file():
            raise ValueError('The selected cookies.txt file no longer exists. Select it again or clear it.')
        cookie_copy = Path(workdir) / 'session.txt'
        shutil.copyfile(source, cookie_copy)
        options['cookiefile'] = str(cookie_copy)
    return options


def track_from_info(info, *, album='', number='', albumartist=''):
    guessed_title, guessed_artist = guess_metadata(
        info.get('title') or 'Untitled', info.get('channel') or info.get('uploader') or 'Unknown Artist')
    artists = info.get('artists') or []
    artist = info.get('artist') or ', '.join(artists) or guessed_artist
    thumbnails = info.get('thumbnails') or []
    artwork = info.get('thumbnail') or (thumbnails[-1].get('url', '') if thumbnails else '')
    number_value = info.get('track_number') or number
    video_id = info.get('id') or ''
    url = info.get('webpage_url') or info.get('url') or ''
    if urlparse(url).hostname not in ('www.youtube.com', 'youtube.com', 'music.youtube.com', 'youtu.be'):
        url = f'https://www.youtube.com/watch?v={video_id}'
    return Track(
        url=url, video_id=video_id, title=info.get('track') or guessed_title,
        artist=artist, album=info.get('album') or album,
        albumartist=info.get('album_artist') or albumartist,
        track=str(number_value) if number_value else '',
        year=str(info.get('release_year') or '') or str(info.get('release_date') or '')[:4],
        genre=info.get('genre') or '', artwork=artwork,
    )


def clean_album_name(title, artist=''):
    if artist:
        title = re.sub(r'^' + re.escape(artist) + r'\s*[-–—:]\s*', '', title, flags=re.I)
    return re.sub(r'\s*[\[(](?:full album|official album)[\])]\s*', ' ', title, flags=re.I).strip()


def preview(url, album_mode='Auto', *, cookies_file=None, workdir=None, report=lambda *_: None):
    from yt_dlp import YoutubeDL
    parsed = validate_url(url)
    playlist_id = parse_qs(parsed.query).get('list', [''])[0]
    playlist = bool(playlist_id)
    album_mode = {True: 'Album', False: 'Mixed playlist'}.get(album_mode, album_mode)
    treat_as_album = album_mode == 'Album' or (album_mode == 'Auto' and is_album_playlist(url))
    context = nullcontext(workdir) if workdir else tempfile.TemporaryDirectory(prefix='ytd3-preview-')
    with context as temporary:
        options = extractor_options(temporary, cookies_file, report)
        options.update({'extract_flat': 'in_playlist' if playlist else False, 'skip_download': True,
                        'noplaylist': not playlist, 'ignoreerrors': False})
        # A Music watch URL with list= explicitly means the entire playlist.
        request_url = f'https://www.youtube.com/playlist?list={playlist_id}' if playlist else url
        report('status', 'Reading playlist details…' if playlist else 'Reading song details…')
        try:
            with YoutubeDL(options) as downloader:
                info = downloader.extract_info(request_url, download=False)
                if not info:
                    raise ValueError('No available songs were found in this link.')
                entries = list(info.get('entries') or []) if playlist else [info]
        except Exception as exc:
            raise classify_download_error(exc) from exc
    usable = [entry for entry in entries if entry and entry.get('availability') not in ('private', 'premium_only', 'subscriber_only')
              and entry.get('title') not in ('[Private video]', '[Deleted video]')]
    if len(usable) != len(entries):
        report('warning', f'{len(entries) - len(usable)} unavailable playlist item(s) were skipped; original track positions are kept.')
    if not usable:
        raise ValueError('No available songs were found in this link.')
    album = info.get('album') or clean_album_name(info.get('title') or '') if treat_as_album else ''
    tracks = []
    for index, entry in enumerate(entries, 1):
        if entry not in usable:
            continue
        number = str(entry.get('playlist_index') or index) if treat_as_album else ''
        tracks.append(track_from_info(entry, album=album, number=number))
    if treat_as_album:
        artists = {track.artist for track in tracks}
        albumartist = tracks[0].artist if len(artists) == 1 else 'Various Artists'
        for track in tracks:
            track.albumartist = track.albumartist or albumartist
            track.album = clean_album_name(track.album, albumartist)
    return tracks


def validate_track(track):
    if not track.title.strip() or not track.artist.strip():
        raise ValueError('Each song needs a title and artist. Select the song to edit it.')
    if track.year and not re.fullmatch(r'\d{4}', track.year):
        raise ValueError('Year must contain four digits, or be blank.')
    if track.track and not re.fullmatch(r'[1-9]\d*(?:/[1-9]\d*)?', track.track):
        raise ValueError('Track number must look like 1 or 1/12, or be blank.')
    if '/' in track.track:
        number, total = map(int, track.track.split('/'))
        if number > total:
            raise ValueError('Track number cannot be greater than the track total.')
    if track.artwork:
        parsed = urlparse(track.artwork)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname:
            raise ValueError('Artwork must be an HTTP(S) image URL, or blank.')


def safe_filename(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:150].rstrip(' .')
    if not value:
        value = 'Untitled'
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', value, re.I):
        value = '_' + value
    return value


def available_path(folder, stem):
    path = Path(folder) / (stem + '.mp3')
    number = 2
    while path.exists():
        path = Path(folder) / f'{stem} ({number}).mp3'
        number += 1
    return path


def ffmpeg_path():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def convert(source, destination):
    command = [ffmpeg_path(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
               '-i', str(source), '-vn', '-map_metadata', '-1', '-c:a', 'libmp3lame',
               '-q:a', '0', str(destination)]
    result = subprocess.run(command, capture_output=True, text=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Audio conversion failed: ' + result.stderr[-1500:])
    if not Path(destination).exists() or Path(destination).stat().st_size == 0:
        raise RuntimeError('Audio conversion produced an empty file.')


def write_tags(path, track):
    from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB, TRCK, TDRC, TCON, APIC, WOAS
    tags = ID3()
    for frame, value in ((TIT2, track.title), (TPE1, track.artist),
                         (TPE2, track.albumartist), (TALB, track.album),
                         (TRCK, track.track), (TDRC, track.year), (TCON, track.genre)):
        if value:
            tags.add(frame(encoding=3, text=[value]))
    tags.add(WOAS(url=track.url))
    warning = ''
    if track.artwork:
        try:
            request = Request(track.artwork, headers={'User-Agent': 'YTD3/0.3'})
            with urlopen(request, timeout=15) as response:
                data = response.read(10 * 1024 * 1024 + 1)
            if len(data) > 10 * 1024 * 1024:
                raise ValueError('Image exceeds 10 MB.')
            if data.startswith(b'\xff\xd8\xff'):
                mime = 'image/jpeg'
            elif data.startswith(b'\x89PNG\r\n\x1a\n'):
                mime = 'image/png'
            else:
                raise ValueError('Artwork is not a JPEG or PNG image.')
            tags.add(APIC(encoding=3, mime=mime, type=3, desc='Cover', data=data))
        except Exception as exc:
            warning = f'Artwork skipped: {format_error(exc)}'
    tags.save(path, v2_version=3)
    return warning


def publish_file(source, folder, stem):
    # Both operations atomically fail if target exists. No empty reservation
    # file is left behind if Cancel terminates the worker at this boundary.
    while True:
        target = available_path(folder, stem)
        try:
            if os.name == 'nt':
                os.rename(source, target)
            else:
                os.link(source, target)
            return target
        except FileExistsError:
            continue


def fetch_audio(url, temporary, progress=lambda percent: None, *,
                cookies_file=None, session_dir=None, report=lambda *_: None):
    # Keep session copies out of the music folder, which may be shared/synced.
    context = nullcontext(session_dir) if session_dir else tempfile.TemporaryDirectory(prefix='ytd3-session-')
    with context as private:
        return _fetch_audio(url, temporary, progress, cookies_file=cookies_file,
                            session_dir=private, report=report)


def _fetch_audio(url, temporary, progress, *, cookies_file, session_dir, report):
    from yt_dlp import YoutubeDL
    temporary = Path(temporary)
    options = extractor_options(session_dir, cookies_file, report)
    last_progress = 0

    def callback(data):
        nonlocal last_progress
        now = time.monotonic()
        if data.get('status') == 'downloading' and now - last_progress > 0.2:
            total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
            if total:
                progress(min(100, data.get('downloaded_bytes', 0) * 100 / total))
            last_progress = now
        elif data.get('status') == 'finished':
            progress(100)

    options.update({'format': 'bestaudio/best', 'noplaylist': True, 'ignoreerrors': False,
                    'outtmpl': str(temporary / 'source.%(ext)s'), 'overwrites': True,
                    'progress_hooks': [callback], 'nopart': False})
    report('status', 'Downloading audio…')
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            if not info:
                raise RuntimeError('The downloader returned no audio information.')
            downloads = info.get('requested_downloads') or []
            source = Path(downloads[0]['filepath']) if downloads and downloads[0].get('filepath') else Path(downloader.prepare_filename(info))
    except Exception as exc:
        raise classify_download_error(exc) from exc
    if source.parent.resolve() != temporary.resolve() or not source.is_file():
        raise RuntimeError('The downloader did not produce an audio file.')
    return source


def source_video_id(url):
    try:
        parsed = validate_url(url)
    except ValueError:
        return ''
    if parsed.hostname in ('youtu.be', 'www.youtu.be'):
        return parsed.path.strip('/').split('/')[0]
    return parse_qs(parsed.query).get('v', [''])[0]


def matching_existing_download(track, folder):
    """Reuse an app-created MP3 only when its source and text tags match."""
    from mutagen import MutagenError
    from mutagen.mp3 import MP3
    stem = safe_filename(f'{track.artist} - {track.title}')
    candidates = [Path(folder) / f'{stem}.mp3']
    candidates.extend(Path(folder).glob(glob.escape(stem) + ' ([0-9]*).mp3'))
    expected = {'TIT2': track.title, 'TPE1': track.artist, 'TALB': track.album,
                'TPE2': track.albumartist, 'TRCK': track.track, 'TDRC': track.year, 'TCON': track.genre}
    video_id = source_video_id(track.url)
    if not video_id:
        return None
    for candidate in candidates:
        try:
            if not candidate.is_file() or not candidate.stat().st_size:
                continue
            audio = MP3(candidate)
            if not audio.tags or audio.info.length <= 0:
                continue
            tags = audio.tags
            if not any(source_video_id(frame.url) == video_id for frame in tags.getall('WOAS')):
                continue
            if all(str(tags.get(key, '')) == value for key, value in expected.items()):
                return candidate
        except (OSError, ValueError, MutagenError):
            continue
    return None


def download_track(track, folder, progress=lambda percent: None, *, workdir=None,
                   cookies_file=None, session_dir=None, report=lambda *_: None):
    validate_track(track)
    validate_url(track.url)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    existing = matching_existing_download(track, folder)
    if existing:
        report('status', 'Keeping an existing download with matching source and tags.')
        progress(100)
        return existing, 'Existing matching download kept (including its artwork).'
    context = nullcontext(workdir) if workdir else tempfile.TemporaryDirectory(prefix='.ytd3-', dir=folder)
    with context as temporary:
        temporary = Path(temporary)
        source = fetch_audio(track.url, temporary, progress, cookies_file=cookies_file,
                             session_dir=session_dir, report=report)
        converted = temporary / 'converted.mp3'
        report('status', 'Converting to MP3…')
        convert(source, converted)
        report('status', 'Writing song details and artwork…')
        warning = write_tags(converted, track)
        target = publish_file(converted, folder, safe_filename(f'{track.artist} - {track.title}'))
    return target, warning
