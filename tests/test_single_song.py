from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ytd_core as core
from ytd_smoke import make_tone


RADIO_SONG_URL = 'https://music.youtube.com/watch?v=GNCd_ERZvZM&list=RDAMVMGNCd_ERZvZM'
SINGLE_SONG_URL = 'https://www.youtube.com/watch?v=GNCd_ERZvZM'


class SingleSongTests(unittest.TestCase):
    def metadata(self):
        return {'id': 'GNCd_ERZvZM', 'title': 'Example Artist - Example Song',
                'track': 'Example Song', 'artist': 'Example Artist', 'album': 'Example Album',
                'track_number': 3, 'webpage_url': RADIO_SONG_URL}

    def test_watch_share_and_shorts_radio_links_select_only_the_video(self):
        for url in (RADIO_SONG_URL,
                    'https://www.youtube.com/watch?v=GNCd_ERZvZM&list=RDGNCd_ERZvZM',
                    'https://youtu.be/GNCd_ERZvZM?list=RDAMVMGNCd_ERZvZM',
                    'https://www.youtube.com/shorts/GNCd_ERZvZM?list=RDGNCd_ERZvZM'):
            with self.subTest(url=url):
                self.assertEqual(core.preview_target(url), (SINGLE_SONG_URL, ''))

    def test_saved_album_playlist_links_keep_playlist_behavior(self):
        for list_id in ('OLAK5uy_example', 'PLexample', 'UUexample'):
            with self.subTest(list_id=list_id):
                target, playlist = core.preview_target('https://music.youtube.com/watch?v=GNCd_ERZvZM&list=' + list_id)
                self.assertEqual(playlist, list_id)
                self.assertEqual(target, 'https://www.youtube.com/playlist?list=' + list_id)

    def test_radio_link_without_a_song_has_actionable_message(self):
        with self.assertRaisesRegex(ValueError, 'watch or share URL'):
            core.preview('https://www.youtube.com/playlist?list=RDAMVMGNCd_ERZvZM')

    def test_reported_radio_song_previews_one_song_with_or_without_session(self):
        with tempfile.TemporaryDirectory() as folder:
            session = Path(folder) / 'cookies.txt'
            session.write_text('# Netscape HTTP Cookie File\n', encoding='utf-8')
            original = session.read_bytes()
            for cookies_file in (None, str(session)):
                with self.subTest(session_selected=bool(cookies_file)), patch('yt_dlp.YoutubeDL') as factory:
                    downloader = factory.return_value.__enter__.return_value
                    downloader.extract_info.return_value = self.metadata()
                    tracks = core.preview(RADIO_SONG_URL, cookies_file=cookies_file)
                    downloader.extract_info.assert_called_once_with(SINGLE_SONG_URL, download=False)
                    options = factory.call_args.args[0]
                    self.assertTrue(options['noplaylist'])
                    self.assertFalse(options['extract_flat'])
                    self.assertNotIn('extractor_args', options)
                    self.assertEqual('cookiefile' in options, bool(cookies_file))
                    self.assertEqual(len(tracks), 1)
                    self.assertEqual(tracks[0].url, SINGLE_SONG_URL)
                    self.assertEqual((tracks[0].title, tracks[0].artist, tracks[0].album, tracks[0].track),
                                     ('Example Song', 'Example Artist', 'Example Album', '3'))
            self.assertEqual(session.read_bytes(), original)

    def test_reported_single_link_saves_one_tagged_mp3_without_extracting_radio_mix(self):
        with patch('yt_dlp.YoutubeDL') as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = self.metadata()
            track = core.preview(RADIO_SONG_URL)[0]
        track.artwork = ''  # This integration fixture focuses on audio and tags.

        def fetch(url, temporary, *args, **kwargs):
            self.assertEqual(url, SINGLE_SONG_URL)
            source = Path(temporary) / 'source.wav'
            make_tone(source)
            return source

        with tempfile.TemporaryDirectory() as folder:
            with patch('ytd_core.fetch_audio', side_effect=fetch) as download:
                path, warning = core.download_track(track, folder)
            download.assert_called_once()
            self.assertEqual(path, Path(folder) / 'Example Album' / 'Example Song.mp3')
            self.assertEqual(core.read_saved_tags(path), {'title': 'Example Song', 'artist': 'Example Artist',
                                                        'album': 'Example Album', 'track': '3'})
            self.assertEqual(len(list(Path(folder).rglob('*.mp3'))), 1)
            self.assertEqual(warning, '')
