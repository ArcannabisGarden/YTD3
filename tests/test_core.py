import math
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from mutagen.mp3 import MP3
from mutagen.id3 import ID3
import ytd_core as core


class CoreTests(unittest.TestCase):
    def track(self, **changes):
        values = dict(url='https://www.youtube.com/watch?v=example', video_id='example',
                      title='Song (Live)', artist='Artist', artwork='')
        values.update(changes)
        return core.Track(**values)

    def test_cleanup_preserves_meaningful_words_and_versions(self):
        self.assertEqual(core.clean_title('Radiohead - Videotape (Live) [Official Video]'),
                         'Radiohead - Videotape (Live)')
        self.assertEqual(core.clean_title('Audiohead (Remix) feat. Official'),
                         'Audiohead (Remix) feat. Official')

    def test_artist_guess_and_topic_channel(self):
        self.assertEqual(core.guess_metadata('Song (Remix)', 'Artist - Topic'),
                         ('Song (Remix)', 'Artist'))
        self.assertEqual(core.guess_metadata('Singer – Song (Live)', 'Uploader'),
                         ('Song (Live)', 'Singer'))

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

    def test_duplicate_names_do_not_replace_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / 'Artist - Song.mp3'
            first.write_bytes(b'keep')
            self.assertEqual(core.available_path(folder, 'Artist - Song').name, 'Artist - Song (2).mp3')
            self.assertEqual(first.read_bytes(), b'keep')

    def test_playlist_album_is_opt_in(self):
        videos = [SimpleNamespace(title='A - One', author='Uploader', watch_url='https://youtu.be/1',
                                  video_id='1', thumbnail_url='https://example.com/1.jpg'),
                  SimpleNamespace(title='B - Two', author='Uploader', watch_url='https://youtu.be/2',
                                  video_id='2', thumbnail_url='https://example.com/2.jpg')]
        playlist = SimpleNamespace(title='Collection', videos=videos)
        with patch('pytubefix.Playlist', return_value=playlist):
            mixed = core.preview('https://youtube.com/playlist?list=arbitrary')
            album = core.preview('https://youtube.com/playlist?list=arbitrary', album_mode=True)
        self.assertTrue(all(not t.album and not t.track for t in mixed))
        self.assertEqual(album[1].track, '2')
        self.assertEqual(album[0].albumartist, 'Various Artists')
        self.assertEqual(album[0].album, 'Collection')

    def make_tone(self, path):
        with wave.open(str(path), 'wb') as audio:
            audio.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
            audio.writeframes(b''.join(struct.pack('<h', int(10000 * math.sin(2 * math.pi * 440 * i / 44100)))
                                       for i in range(22050)))

    def test_real_conversion_and_metadata_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'tone.wav'
            output = Path(folder) / 'tone.mp3'
            self.make_tone(source)
            core.convert(source, output)
            warning = core.write_tags(output, self.track(album='Album', albumartist='Group',
                                                        track='2/12', year='2024', genre='Rock'))
            self.assertEqual(warning, '')
            audio = MP3(output)
            self.assertGreater(audio.info.length, 0.4)
            self.assertEqual(str(audio.tags['TIT2']), 'Song (Live)')
            self.assertEqual(str(audio.tags['TPE2']), 'Group')
            self.assertEqual(str(audio.tags['TRCK']), '2/12')
            self.assertEqual(str(audio.tags['TDRC']), '2024')
            self.assertEqual(audio.tags.version, (2, 3, 0))
            self.assertTrue(source.exists())

    def test_artwork_failure_still_saves_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tags.mp3'
            path.write_bytes(b'')
            with patch('ytd_core.urlopen', side_effect=TimeoutError('test timeout')):
                warning = core.write_tags(path, self.track(artwork='https://example.com/cover.jpg'))
            self.assertIn('Artwork skipped', warning)
            self.assertEqual(str(ID3(path)['TPE1']), 'Artist')
            self.assertFalse(ID3(path).getall('APIC'))

    def test_download_failure_cleans_temporary_files(self):
        class Stream:
            abr = '128kbps'
            subtype = 'wav'
            def download(stream, output_path, filename):
                path = Path(output_path) / filename
                path.write_bytes(b'broken source')
                return str(path)
        video = SimpleNamespace(streams=SimpleNamespace(filter=lambda **_: [Stream()]))
        with tempfile.TemporaryDirectory() as folder:
            with patch('pytubefix.YouTube', return_value=video), \
                 patch('ytd_core.convert', side_effect=RuntimeError('conversion failed')):
                with self.assertRaises(RuntimeError):
                    core.download_track(self.track(), folder)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_download_pipeline_avoids_overwrite_and_keeps_metadata(self):
        test = self
        class Stream:
            abr = '128kbps'
            subtype = 'wav'
            def download(stream, output_path, filename):
                path = Path(output_path) / filename
                test.make_tone(path)
                return str(path)
        video = SimpleNamespace(streams=SimpleNamespace(filter=lambda **_: [Stream()]))
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / 'Artist - Song (Live).mp3'
            existing.write_bytes(b'original')
            with patch('pytubefix.YouTube', return_value=video):
                target, warning = core.download_track(self.track(), folder)
            self.assertEqual(existing.read_bytes(), b'original')
            self.assertEqual(target.name, 'Artist - Song (Live) (2).mp3')
            self.assertEqual(str(ID3(target)['TIT2']), 'Song (Live)')
            self.assertEqual(warning, '')
            self.assertEqual(len(list(Path(folder).iterdir())), 2)


if __name__ == '__main__':
    unittest.main()
