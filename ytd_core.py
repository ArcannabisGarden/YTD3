"""Download and tagging operations, independent of the desktop interface."""
from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess
import tempfile
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
    # Remove only complete promotional labels. Keep Live, Remix, feat., etc.
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


def is_youtube_block(error):
    from pytubefix.exceptions import BotDetection
    return isinstance(error, BotDetection)


def format_error(error):
    if is_youtube_block(error):
        return (
            'YouTube is asking for verification and blocked this request. '
            'Open the link in your browser and check that it plays on your normal connection, '
            'then try again later. If it keeps happening, this app may need a downloader update. '
            'Repeated retries will not resolve a YouTube block.'
        )
    return str(error)


def youtube_video(url, **kwargs):
    from pytubefix import YouTube
    # WEB activates pytubefix's automatic PO-token support using the bundled
    # Node runtime. Do not use use_po_token=True: it prompts on stdin, which
    # a windowed desktop app does not have.
    return YouTube(url, client='WEB', **kwargs)


def preview(url, album_mode=False):
    from pytubefix import Playlist
    parsed = validate_url(url)
    is_playlist = bool(parse_qs(parsed.query).get('list'))
    playlist = Playlist(url) if is_playlist else None
    # Playlist.videos silently creates default-client YouTube objects. Build
    # each video through the same WEB client used by single songs/downloads.
    videos = (youtube_video(item) for item in playlist.video_urls) if playlist else [youtube_video(url)]
    tracks = []
    for index, video in enumerate(videos, 1):
        title, artist = guess_metadata(video.title, video.author)
        tracks.append(Track(
            url=video.watch_url, video_id=video.video_id, title=title, artist=artist,
            album=playlist.title if playlist and album_mode else '',
            track=str(index) if playlist and album_mode else '',
            artwork=video.thumbnail_url,
        ))
    if not tracks:
        raise ValueError('No available songs were found in this link.')
    if playlist and album_mode:
        artists = {t.artist for t in tracks}
        albumartist = tracks[0].artist if len(artists) == 1 else 'Various Artists'
        for track in tracks:
            track.albumartist = albumartist
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
            request = Request(track.artwork, headers={'User-Agent': 'YTD3/1.0'})
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
            warning = f'Artwork skipped: {exc}'
    tags.save(path, v2_version=3)
    return warning


def download_track(track, folder, progress=lambda percent: None):
    validate_track(track)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    def callback(stream, chunk, remaining):
        total = stream.filesize
        if total:
            progress(min(100, (total - remaining) * 100 / total))

    video = youtube_video(track.url, on_progress_callback=callback)
    streams = list(video.streams.filter(only_audio=True))
    if not streams:
        raise RuntimeError('No audio streams are available for this song.')
    # Compare reported audio bitrate rather than container file size.
    stream = max(streams, key=lambda s: int(re.sub(r'\D', '', s.abr or '') or 0))
    stem = safe_filename(f'{track.artist} - {track.title}')
    with tempfile.TemporaryDirectory(prefix='.ytd3-', dir=folder) as temporary:
        source = stream.download(output_path=temporary, filename='source.' + stream.subtype)
        converted = Path(temporary) / 'converted.mp3'
        convert(source, converted)
        warning = write_tags(converted, track)
        # Reserve the name atomically: never overwrite another file.
        while True:
            target = available_path(folder, stem)
            try:
                descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(descriptor)
                break
            except FileExistsError:
                continue
        try:
            os.replace(converted, target)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return target, warning
