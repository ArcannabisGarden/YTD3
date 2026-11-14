from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mutagen.mp3 import MP3
from mutagen.id3 import ID3
import ytd_core as core
from ytd_smoke import make_tone, worker_diagnostic


class CoreTests(unittest.TestCase):
    def track(self, **changes):
        values = dict(url='https://www.youtube.com/watch?v=example', video_id='example',
                      title='Song (Live)', artist='Artist', artwork='')
        values.update(changes)
        return core.Track(**values)

    def extract_preview(self, info, url='https://youtube.com/playlist?list=OLAK5uy_example', mode='Auto'):
        with patch('yt_dlp.YoutubeDL') as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = info
            tracks = core.preview(url, mode)
        return tracks, factory.call_args.args[0]

    def playlist(self):
        return {'title': 'Artist - Album', 'entries': [
            {'id': 'first', 'title': 'One (Live)', 'channel': 'Artist - Topic'},
            {'id': 'second', 'title': 'Two', 'channel': 'Artist - Topic'}]}

    def test_title_cleanup_preserves_versions_and_words(self):
        self.assertEqual(core.clean_title('Radiohead - Videotape (Live) [Official Video]'), 'Radiohead - Videotape (Live)')
        self.assertEqual(core.clean_title('Audiohead (Remix) feat. Official'), 'Audiohead (Remix) feat. Official')

    def test_artist_guess(self):
        self.assertEqual(core.guess_metadata('Song (Remix)', 'Artist - Topic'), ('Song (Remix)', 'Artist'))
        self.assertEqual(core.guess_metadata('Singer – Song (Live)', 'Uploader'), ('Song (Live)', 'Singer'))

    def test_url_validation(self):
        for url in ['file:///etc/passwd', 'https://youtube.com.evil.test/watch?v=x',
                    'https://evil.test/youtu.be/x', 'https://user@youtube.com/watch?v=x']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                core.validate_url(url)
        core.validate_url('https://music.youtube.com/watch?v=x')
        core.validate_url('https://youtu.be/x')

    def test_optional_metadata_validation(self):
        core.validate_track(self.track(track='2/12', year='2024'))
        for changes in [dict(title=''), dict(artist=''), dict(track='0'), dict(track='3/2'),
                        dict(year='24'), dict(artwork='file:///cover.jpg')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                core.validate_track(self.track(**changes))

    def test_windows_filenames(self):
        self.assertEqual(core.safe_filename('CON'), '_CON')
        self.assertEqual(core.safe_filename('a/b:c? '), 'a_b_c_')
        self.assertEqual(core.safe_filename('...'), 'Untitled')
        self.assertLessEqual(len(core.safe_filename('x' * 500)), 150)

    def test_album_playlist_gets_album_and_track_numbers_by_default(self):
        tracks, options = self.extract_preview(self.playlist())
        self.assertEqual([t.album for t in tracks], ['Album', 'Album'])
        self.assertEqual([t.track for t in tracks], ['1', '2'])
        self.assertEqual(tracks[0].albumartist, 'Artist')
        self.assertEqual(options['extract_flat'], 'in_playlist')
        self.assertFalse(options['noplaylist'])

    def test_mixed_playlist_does_not_invent_album_or_track(self):
        tracks, _ = self.extract_preview(self.playlist(), mode='Mixed playlist')
        self.assertTrue(all(not t.album and not t.track for t in tracks))
        # Structured song metadata is still preserved in a mixed playlist.
        info = self.playlist()
        info['entries'][0].update(album='Real Album', track_number=4)
        tracks, _ = self.extract_preview(info, mode='Mixed playlist')
        self.assertEqual(tracks[0].album, 'Real Album')
        self.assertEqual(tracks[0].track, '4')

    def test_explicit_album_mode_for_regular_playlist(self):
        tracks, _ = self.extract_preview(self.playlist(), url='https://youtube.com/playlist?list=PLexample', mode='Album')
        self.assertEqual(tracks[1].album, 'Album')
        self.assertEqual(tracks[1].track, '2')

    def test_album_track_positions_survive_unavailable_entry(self):
        info = self.playlist()
        info['entries'].insert(1, {'id': 'private', 'title': '[Private video]'})
        tracks, _ = self.extract_preview(info)
        self.assertEqual([t.track for t in tracks], ['1', '3'])

    def test_single_song_uses_structured_music_metadata(self):
        info = dict(id='a', title='Uploader title [Official Video]', channel='Uploader',
                    track='Actual Song (Remix)', artist='Singer', album='Real Album',
                    track_number=7, release_year=2024, album_artist='Group')
        tracks, options = self.extract_preview(info, url='https://youtu.be/a')
        self.assertTrue(options['noplaylist'])
        self.assertEqual((tracks[0].title, tracks[0].artist, tracks[0].album, tracks[0].track, tracks[0].year),
                         ('Actual Song (Remix)', 'Singer', 'Real Album', '7', '2024'))
        self.assertEqual(tracks[0].albumartist, 'Group')

    def test_sabr_and_network_errors_stop_batch_and_preserve_reason(self):
        for message in ['SABR Maximum reload attempts reached. Stream protection status: PoToken PENDING',
                        'HTTP Error 403: Forbidden', 'Connection reset by peer', 'Read timed out']:
            with self.subTest(message=message):
                error = core.classify_download_error(RuntimeError(message))
                self.assertTrue(error.stop_batch)
                self.assertIn(message, str(error))
        self.assertFalse(core.classify_download_error(ValueError('Video removed by uploader')).stop_batch)

    def test_signed_urls_are_removed_from_logs(self):
        error = core.format_error(RuntimeError('HTTP Error 403: https://media.example/song?token=secret'))
        self.assertIn('HTTP Error 403', error)
        self.assertNotIn('secret', error)

    def test_session_uses_private_copy_and_bounded_retries(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            session = folder / 'original.txt'
            session.write_text('# Netscape HTTP Cookie File\n')
            temporary = folder / 'job'
            temporary.mkdir()
            options = core.extractor_options(temporary, str(session))
            Path(options['cookiefile']).write_text('changed by downloader')
            self.assertEqual(session.read_text(), '# Netscape HTTP Cookie File\n')
            self.assertEqual(options['socket_timeout'], 15)
            self.assertEqual(options['retries'], 2)
            self.assertEqual(options['fragment_retries'], 2)
            self.assertIn('node', options['js_runtimes'])

    def test_real_conversion_and_metadata_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'tone.wav'
            output = Path(folder) / 'tone.mp3'
            make_tone(source)
            core.convert(source, output)
            core.write_tags(output, self.track(album='Album', albumartist='Group', track='2/12', year='2024', genre='Rock'))
            audio = MP3(output)
            self.assertGreater(audio.info.length, 0.4)
            for key, expected in [('TIT2', 'Song (Live)'), ('TPE2', 'Group'), ('TRCK', '2/12'), ('TDRC', '2024')]:
                self.assertEqual(str(audio.tags[key]), expected)
            self.assertEqual(audio.tags.version, (2, 3, 0))

    def test_artwork_failure_still_saves_tags(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tags.mp3'
            path.write_bytes(b'')
            with patch('ytd_core.urlopen', side_effect=TimeoutError('test timeout')):
                warning = core.write_tags(path, self.track(artwork='https://example.com/cover.jpg'))
            self.assertIn('Artwork skipped', warning)
            self.assertEqual(str(ID3(path)['TPE1']), 'Artist')
            self.assertFalse(ID3(path).getall('APIC'))

    def test_download_preserves_existing_files_and_user_edits(self):
        def audio(url, temporary, *args, **kwargs):
            path = Path(temporary) / 'source.wav'
            make_tone(path)
            return path
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / 'Artist - Song (Live).mp3'
            existing.write_bytes(b'keep')
            with patch('ytd_core.fetch_audio', side_effect=audio):
                output, warning = core.download_track(self.track(album='My edits', track='3'), folder)
            self.assertEqual(existing.read_bytes(), b'keep')
            self.assertEqual(output.name, 'Artist - Song (Live) (2).mp3')
            self.assertEqual(str(ID3(output)['TALB']), 'My edits')
            self.assertEqual(str(ID3(output)['TRCK']), '3')
            self.assertEqual(warning, '')
            self.assertEqual(len(list(Path(folder).iterdir())), 2)

    def test_conversion_failure_leaves_no_partial_output(self):
        def audio(url, temporary, *args, **kwargs):
            path = Path(temporary) / 'source.wav'
            make_tone(path)
            return path
        with tempfile.TemporaryDirectory() as folder:
            with patch('ytd_core.fetch_audio', side_effect=audio), \
                 patch('ytd_core.convert', side_effect=RuntimeError('conversion failed')):
                with self.assertRaisesRegex(RuntimeError, 'conversion failed'):
                    core.download_track(self.track(), folder)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_real_engine_local_http_node_and_ffmpeg(self):
        with tempfile.TemporaryDirectory() as folder:
            result = worker_diagnostic(folder)
        self.assertTrue(all(result.values()))


if __name__ == '__main__':
    unittest.main()
