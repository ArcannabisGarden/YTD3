from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yt_dlp.utils import DownloadError
import ytd_core as core
from ytd_smoke import verify_public_album_fallback


class PlaylistPreviewAuthTests(unittest.TestCase):
    def preview_options(self, url, cookies_file=None):
        metadata = {'title': 'album - Disclaimer II', 'entries': [
            {'id': 'example', 'title': 'seether - Gasoline', 'channel': 'Seether - Topic'}]}
        with patch('yt_dlp.YoutubeDL') as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = metadata
            tracks = core.preview(url, cookies_file=cookies_file)
        self.assertEqual((tracks[0].title, tracks[0].artist, tracks[0].album), ('Gasoline', 'Seether', 'Disclaimer II'))
        return factory.call_args.args[0]

    def test_public_album_preview_uses_documented_fallback_with_or_without_cookies(self):
        with tempfile.TemporaryDirectory() as folder:
            session = Path(folder) / 'session.txt'
            session.write_text('# Netscape HTTP Cookie File\n', encoding='utf-8')
            original = session.read_bytes()
            for cookies in (None, str(session)):
                with self.subTest(cookies_selected=bool(cookies)):
                    options = self.preview_options('https://music.youtube.com/playlist?list=OLAK5uy_example', cookies)
                    self.assertEqual(options['extractor_args']['youtubetab']['skip'], ['authcheck'])
                    self.assertTrue(options['skip_download'])
                    self.assertEqual('cookiefile' in options, bool(cookies))
                    if cookies:
                        self.assertNotEqual(options['cookiefile'], str(session))
            self.assertEqual(session.read_bytes(), original)

    def test_regular_or_private_playlist_keeps_authentication_guard(self):
        options = self.preview_options('https://www.youtube.com/playlist?list=PLprivate')
        self.assertNotIn('extractor_args', options)

    def test_video_download_options_keep_the_default_guard_and_session(self):
        with tempfile.TemporaryDirectory() as folder:
            public = core.extractor_options(folder, public_album_preview=True)
            normal = core.extractor_options(folder)
        self.assertIn('extractor_args', public)
        self.assertNotIn('extractor_args', normal)

    def test_real_yt_dlp_guard_and_api_fallback_when_webpage_is_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(verify_public_album_fallback(folder))

    def test_authcheck_failure_reports_preview_problem_instead_of_bad_cookie_advice(self):
        error = DownloadError('ERROR: [youtube:tab] OLAK5uy_example: Playlists that require authentication may not '
            'extract correctly without a successful webpage download. If you are not downloading private content, '
            'pass "--extractor-args youtubetab:skip=authcheck" to skip this check')
        result = core.classify_download_error(error)
        self.assertTrue(result.stop_batch)
        self.assertIn('Playlist preview failed', str(result))
        self.assertIn('webpage could not be loaded', str(result))
        self.assertNotIn('--extractor-args', str(result))

    def test_public_warning_describes_fallback_and_retains_other_warnings(self):
        messages = []
        logger = core.QuietLogger(lambda *item: messages.append(item), public_album_preview=True)
        logger.warning('Playlists that require authentication may not extract correctly without a successful webpage download')
        logger.warning('HTTP Error 403 while fetching the album page')
        self.assertIn('public track list', messages[0][1])
        self.assertIn('HTTP Error 403', messages[1][1])
