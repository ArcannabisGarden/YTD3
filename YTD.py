import sys
import requests
import urllib.parse as urlparse
import os
import re
import subprocess
from pytubefix import YouTube, Playlist
from tqdm import tqdm
from colorama import Fore, Style, init
from pydub import AudioSegment
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, TPE2, TSSE, TENC

init(autoreset=True)
Download_DIR = r'C:\Users\vague\OneDrive\Escritorio\YTD'
link = input("Enter YouTube URL: ")
mp3_path = "song.mp3"

progress_bar = None

class Log:
    @staticmethod
    def info(msg):
        print(Fore.CYAN + msg + Style.RESET_ALL)

    @staticmethod
    def success(msg):
        print(Fore.GREEN + msg + Style.RESET_ALL)

    @staticmethod
    def warn(msg):
        print(Fore.YELLOW + "WARN: " + Style.RESET_ALL + msg)

    @staticmethod
    def error(msg):
        print(Fore.RED + "ERROR: " + Style.RESET_ALL + msg)

    @staticmethod
    def action(msg):
        print(Fore.LIGHTWHITE_EX + ">> " + Style.RESET_ALL + msg)


def convert_to_mp3(file_path):
    mp3_path = os.path.splitext(file_path)[0] + ".mp3"
    audio = AudioSegment.from_file(file_path)
    audio.export(mp3_path, format="mp3", parameters=["-codec:a","libmp3lame","-q:a","0"])
    os.remove(file_path)
    return mp3_path


def progress_function(stream, chunk, bytes_remaining):
    global progress_bar
    if progress_bar:
        progress_bar.update(len(chunk))


def complete_function(stream, file_path):
    global progress_bar
    if progress_bar:
        progress_bar.close()
        progress_bar = None


def is_video_url(url):
    return "watch?v=" in url or "youtu.be/" in url


def get_list_id(url):
    query = urlparse.urlparse(url).query
    params = urlparse.parse_qs(query)
    return params.get("list", [None])[0]


def apply_track_replaygain(mp3_path):
    cmd = ["ffmpeg", "-y", "-i", mp3_path, "-af",
           "replaygain", "-vn", "-acodec", "copy",
           mp3_path + ".rg.mp3"
           ]
    subprocess.run(cmd,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                   )


def split_artist_from_title(title):
    separators = [" - ", " – ", " — ", " : ", "|"]
    for sep in separators:
        if sep not in title:
            continue
        left, right = title.split(sep, 1)
        artist = left.strip()
        track = right.strip()

        track = re.sub(r'\(.*?\)', '', track)
        track = re.sub(r'\[.*?\]', '', track)
        track = track.strip()

        if len(artist) < 2 or len(track) < 2:
            continue
        return artist, track
    return None, None


def clean_artist_name(name):
    if not name:
        return None
    name = name.strip()
    if name.lower().endswith(" - topic"):
        name = name[:-8].strip()
    return name


def clean_album_name(name, artist):
    if not name:
        return None

    if artist:
        artist_re = re.escape(artist)
        name = re.sub(
            rf'^{artist_re}\s*[-–—:|.]\s*',
            '',
            name,
            flags=re.I
        )

    name = re.sub(r'^-\s+', '', name)
    return name.strip()


def normalize_album_name(name):
    if not name:
        return None

    name = re.sub(r'\(.*?\)|\[.*?\]', '', name)
    name = re.sub(
        r'\b(full\s*)?(album|ep|lp|official|playlist)\b',
        '',
        name,
        flags=re.I
    )
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'^-\s+', '', name)

    return name or None


def derive_playlist_album(pl):

    playlist_artist = clean_artist_name(pl.videos[0].author) if pl.videos else None
    album = clean_album_name(pl.title, playlist_artist)
    album = normalize_album_name(album)

    if not album:
        return "Unknown Album"

    return album


def safe_filename(name):

    if not name:
        return ""

    return "".join(
        "꞉" if c == ":" else "_" if c in r'<>"/\|?*' else c
        for c in name
    ).strip()


def normalize_title(title):
    if not title:
        return title
    return re.sub(
        r'\s*(official|lyrics?|video|audio|mv)\s*',
        '',
        title,
        flags=re.I
    ).strip()


def force_strip_artist_prefix(title, artist):
    if not title or not artist:
        return title

    artist_re = re.escape(artist)
    pattern = rf'^{artist_re}\s*[-–—:|]\s*'
    return re.sub(pattern, '', title, flags=re.I).strip()


def clean_track_title(title):
    if not title:
        return title

    title = re.sub(r'\(.*?\)|\[.*?\]', '', title)
    title = re.sub(r'\.{2,}', '.', title)
    title = re.sub(r'\s+', ' ', title)
    return title.strip(" .-_–—:")


def resolve_metadata(yt, *, album, track, artist_hint=None):
    raw_artist = clean_artist_name(artist_hint or yt.author)

    title = normalize_title(yt.title)
    split_artist, split_title = split_artist_from_title(title)

    if split_artist and split_title:
        final_artist = clean_artist_name(split_artist)
        final_title = split_title
    else:
        final_artist = raw_artist
        final_title = force_strip_artist_prefix(title, final_artist)

    final_title = clean_track_title(final_title)

    return {
        "artist": final_artist,
        "title": final_title,
        "album": album,
        "track": track,
    }


def add_id3_tags(mp3_path, metadata, yt):
    try:
        tags = EasyID3(mp3_path)
    except Exception:
        tags = EasyID3()
        tags.save(mp3_path)
        tags = EasyID3(mp3_path)
    tags["title"] = metadata["title"]
    tags["artist"] = metadata["artist"]
    tags["albumartist"] = metadata["artist"]

    if metadata.get("album"):
        tags["album"] = metadata["album"]
    if metadata.get("track"):
        tags["tracknumber"] = str(metadata["track"])
    tags.save()
    audio = ID3(mp3_path)

    if "TPE2" in audio:
        del audio["TPE2"]
    audio["TPE2"] = TPE2(encoding=3,text=[metadata["artist"]])
    audio["TENC"] = TENC(encoding=3, text=["libmp3lame"])
    audio["TSSE"] = TSSE(encoding=3, text=["V0 (VBR)"])

    thumb_url = f"https://img.youtube.com/vi/{yt.video_id}/maxresdefault.jpg"
    response = requests.get(thumb_url)

    if response.status_code != 200 or "image" not in response.headers.get("content-type", ""):
        thumb_url = f"https://img.youtube.com/vi/{yt.video_id}/hqdefault.jpg"
        response = requests.get(thumb_url)

    if response.status_code != 200 or "image" not in response.headers.get("content-type", ""):
        thumb_url = f"https://img.youtube.com/vi/{yt.video_id}/sddefault.jpg"
        response = requests.get(thumb_url)

    img = response.content
    mime = response.headers.get("content-type", "image/jpeg")

    for key in list(audio.keys()):
        if key.startswith("APIC"):
            del audio[key]

    audio.add(APIC(
        encoding=3,mime=mime,type=3,desc="Cover",data=img
    ))
    audio.save(v2_version=3)


playlist_prefixes = ("PL", "UU", "OL")
list_id = get_list_id(link)
is_playlist = (
    list_id is not None
    and any(list_id.startswith(prefix) for prefix in playlist_prefixes)
)


# ==============================================================
# PLAYLIST MODE
# ==============================================================
if is_playlist:
    Log.success("\nDetected: PLAYLIST\n")
    pl = Playlist(link)
    Log.info(f"Playlist Title: {pl.title}")

    playlist_artist = clean_artist_name(pl.videos[0].author) if pl.videos else None

    raw_album = clean_album_name(pl.title, playlist_artist)
    album_name = derive_playlist_album(pl)


    playlist_folder = os.path.join(
        Download_DIR,
        safe_filename(album_name)
    )
    os.makedirs(playlist_folder, exist_ok=True)

    playlist_folder = os.path.join(Download_DIR, safe_filename(album_name))
    os.makedirs(playlist_folder, exist_ok=True)

    Log.info(f"Songs in playlist: {len(pl.videos)}\n")

    for track_number, yt in enumerate(pl.videos, start=1):
        tqdm.write(Fore.LIGHTWHITE_EX + f"\n>> Downloading {track_number}: {yt.title}" + Style.RESET_ALL)

        progress_bar = None
        audio_streams = yt.streams.filter(only_audio=True)
        opus_streams = [s for s in audio_streams if "webm" in s.mime_type]
        if opus_streams:
            best_stream = max(opus_streams, key=lambda s: s.filesize or 0)
        else:
            best_stream = max(audio_streams, key=lambda s: s.filesize or 0)

        progress_bar = tqdm(
            total=best_stream.filesize,
            unit="B",
            unit_scale=True,
            desc=yt.title[:40],
            leave=True,
        )

        yt.register_on_progress_callback(progress_function)
        yt.register_on_complete_callback(complete_function)

        file_path = best_stream.download(playlist_folder)

        safe_title = safe_filename(yt.title)
        new_path = os.path.join(playlist_folder, safe_title + ".webm")
        os.rename(file_path, new_path)
        file_path = new_path

        mp3_path = convert_to_mp3(file_path)
        apply_track_replaygain(mp3_path)
        metadata = resolve_metadata(
            yt, album=album_name, track=track_number, artist_hint=None
        )
        print(metadata)
        add_id3_tags(mp3_path,metadata, yt)

    Log.success("\nPlaylist downloaded and converted to MP3 with track info\n")

# ==============================================================
# SINGLE VIDEO MODE
# ==============================================================
elif is_video_url(link):
    Log.success("\nDetected: single video\n")
    yt = YouTube(link)
    Log.info(f"Title: {yt.title}")

    audio_streams = yt.streams.filter(only_audio=True)
    opus_streams = [s for s in audio_streams if "webm" in s.mime_type]
    if opus_streams:
        best_stream = max(opus_streams, key=lambda s: s.filesize or 0)
    else:
        best_stream = max(audio_streams, key=lambda s: s.filesize or 0)

    progress_bar = tqdm(
        total=best_stream.filesize,
        unit="B",
        unit_scale=True,
        desc=yt.title[:40],
        leave=True
    )

    yt.register_on_progress_callback(progress_function)
    yt.register_on_complete_callback(complete_function)

    file_path = best_stream.download(Download_DIR)
    mp3_path = convert_to_mp3(file_path)
    apply_track_replaygain(mp3_path)

    metadata = resolve_metadata(
        yt, album=None, track=None, artist_hint=yt.author
    )
    add_id3_tags(mp3_path, metadata, yt)

    Log.success("Converted to MP3 with track info\n")
    Log.success("Download complete!")

else:
    Log.error("Invalid link")
    sys.exit(1)