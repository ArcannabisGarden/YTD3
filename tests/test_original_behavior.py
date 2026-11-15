"""Behavior restored from the original YTdownloader.py, including regressions."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from PIL import Image
from mutagen.id3 import ID3, TXXX, USLT
from mutagen.mp3 import MP3
import ytd_core as core
from ytd_smoke import make_tone


def cover_bytes(format='WEBP'):
    image = Image.new('RGBA', (32, 16), (100, 40, 20, 160))
    if format == 'JPEG':
        image = image.convert('RGB')
    result = io.BytesIO()
    image.save(result, format)
    return result.getvalue()


class OriginalBehaviorTests(unittest.TestCase):
    def track(self, **changes):
        values = dict(url='https://www.youtube.com/watch?v=example', video_id='example',
                      title='Gasoline', artist='Seether', album='Disclaimer', albumartist='Seether', track='1')
        values.update(changes)
        return core.Track(**values)

    def test_user_seether_example_cleans_structured_track_field(self):
        track = core.track_from_info({'id': 'example', 'title': 'seether - Gasoline',
                                     'track': 'seether - Gasoline', 'artist': 'Seether'})
        self.assertEqual(track.artist, 'Seether')
        self.assertEqual(track.title, 'Gasoline')

    def test_original_artist_prefix_separators_and_topic_cleanup(self):
        for title in ['seether - Gasoline', 'Seether–Gasoline', 'Seether: Gasoline',
                      'Seether | Gasoline', 'Seether - - Gasoline - [Official Video]']:
            with self.subTest(title=title):
                self.assertEqual(core.guess_metadata(title, 'Seether - Topic'), ('Gasoline', 'Seether'))
        for separator in (' - ', ' – ', ' — ', ' : ', '|'):
            self.assertEqual(core.guess_metadata('Seether' + separator + 'Gasoline', 'Uploader'), ('Gasoline', 'Seether'))

    def test_genuine_title_punctuation_and_versions_remain(self):
        for title in ['Love-Hate', 'Fine Again - Acoustic', '-Human', 'Gasoline (Live)']:
            with self.subTest(title=title):
                track = core.track_from_info({'id': 'a', 'title': title, 'track': title, 'artist': 'Seether'})
                self.assertEqual(track.title, title)
        self.assertEqual(core.clean_track_title(' - Gasoline - '), 'Gasoline')

    def test_regular_playlist_defaults_to_album_name_and_track_order(self):
        info = {'title': 'Seether - - Disclaimer [Full Album]', 'entries': [
            {'id': 'example', 'title': 'seether - Gasoline', 'channel': 'Seether - Topic'}]}
        with patch('yt_dlp.YoutubeDL') as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = info
            tracks = core.preview('https://youtube.com/playlist?list=PLexample')
        self.assertEqual((tracks[0].artist, tracks[0].title, tracks[0].album, tracks[0].track),
                         ('Seether', 'Gasoline', 'Disclaimer', '1'))
        self.assertEqual(core.album_folder(tracks[0], Path('Music')), Path('Music') / 'Disclaimer')

    def test_single_video_does_not_use_its_song_title_as_an_album(self):
        info = {'id': 'example', 'title': 'Gasoline', 'artist': 'Seether'}
        with patch('yt_dlp.YoutubeDL') as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = info
            track = core.preview('https://youtu.be/example')[0]
        self.assertEqual(track.album, '')
        self.assertEqual(core.album_folder(track, Path('Music')), Path('Music'))

    def test_album_cleaning_keeps_actual_album_words_and_safe_colon(self):
        self.assertEqual(core.clean_album_name('Seether - Disclaimer [Full Album]', 'Seether'), 'Disclaimer')
        self.assertEqual(core.clean_album_name('Seether | - Disclaimer - EP', 'Seether'), 'Disclaimer')
        self.assertEqual(core.clean_album_name('The Album'), 'The Album')
        self.assertEqual(core.safe_filename('Album: Part I'), 'Album꞉ Part I')

    def test_reported_disclaimer_ii_album_label_is_not_part_of_album_name(self):
        for title in ('album - Disclaimer II', 'Album: Disclaimer II',
                      'Album - Seether - Disclaimer II', 'Seether - Album - Disclaimer II'):
            with self.subTest(title=title):
                self.assertEqual(core.clean_album_name(title, 'Seether'), 'Disclaimer II')
        self.assertEqual(core.clean_album_name('Album of the Year'), 'Album of the Year')

    def test_lead_artist_prefix_is_removed_with_multiple_artist_metadata(self):
        track = core.track_from_info({'id': 'example', 'track': 'Seether - Broken',
            'title': 'Broken', 'artists': ['Seether', 'Amy Lee'], 'channel': 'Uploader'})
        self.assertEqual(track.title, 'Broken')
        self.assertEqual(track.artist, 'Seether, Amy Lee')
        solo = core.track_from_info({'id': 'example', 'track': 'seether - Gasoline',
            'title': 'Gasoline', 'artists': 'Seether'})
        self.assertEqual((solo.title, solo.artist), ('Gasoline', 'Seether'))

    def test_exact_reported_folder_filename_and_title_are_repaired_together(self):
        info = {'title': 'album - Disclaimer II', 'entries': [
            {'id': 'example', 'title': 'seether - Gasoline', 'track': 'seether - Gasoline',
             'artist': 'Seether', 'channel': 'Seether - Topic', 'thumbnail': 'https://images.example/cover.webp'}]}
        with patch('yt_dlp.YoutubeDL') as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = info
            track = core.preview('https://youtube.com/playlist?list=OLAK5uy_example')[0]
        self.assertEqual(core.relative_output_path(track).as_posix(), 'Disclaimer II/Gasoline.mp3')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrong_folder = root / 'Album - Disclaimer II'
            wrong_folder.mkdir()
            original = wrong_folder / 'Seether - Gasoline.mp3'
            source = root / 'tone.wav'
            make_tone(source)
            core.convert(source, original)
            core.write_tags(original, self.track(title='Seether - Gasoline', album='Album - Disclaimer II'))
            audio = original.read_bytes()[MP3(original).info.frame_offset:]
            with patch('ytd_core.fetch_audio') as download, patch('ytd_core.convert') as encode, \
                 patch('ytd_core.urlopen', return_value=io.BytesIO(cover_bytes())):
                result, _ = core.download_track(track, root)
                download.assert_not_called()
                encode.assert_not_called()
            self.assertEqual(result, root / 'Disclaimer II' / 'Gasoline.mp3')
            self.assertEqual(core.read_saved_tags(result), {'title': 'Gasoline', 'artist': 'Seether',
                                                         'album': 'Disclaimer II', 'track': '1'})
            self.assertEqual(result.read_bytes()[MP3(result).info.frame_offset:], audio)
            self.assertFalse(wrong_folder.exists(), 'only the empty outdated album folder is removed')
            self.assertTrue(root.is_dir(), 'the selected Save to folder must be retained')

    def test_webp_png_gif_and_jpeg_decode_to_embeddable_jpeg(self):
        for format in ('WEBP', 'PNG', 'GIF', 'JPEG'):
            with self.subTest(format=format):
                converted = core.artwork_as_jpeg(cover_bytes(format))
                with Image.open(io.BytesIO(converted)) as image:
                    self.assertEqual(image.format, 'JPEG')
                    self.assertEqual(image.mode, 'RGB')
                    self.assertEqual(image.size, (32, 16))

    def test_webp_is_embedded_despite_url_extension_and_cached_on_repair(self):
        track = self.track(artwork='https://images.example/cover.bin')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tags.mp3'
            path.write_bytes(b'')
            with patch('ytd_core.urlopen', return_value=io.BytesIO(cover_bytes('WEBP'))) as request:
                self.assertEqual(core.write_tags(path, track), '')
                self.assertEqual(core.write_tags(path, track, encoded=False), '')
                request.assert_called_once()
            tags = ID3(path)
            cover = tags.getall('APIC')[0]
            self.assertEqual(cover.mime, 'image/jpeg')
            self.assertEqual(cover.type, 3)
            with Image.open(io.BytesIO(cover.data)) as image:
                self.assertEqual(image.format, 'JPEG')
            self.assertEqual(tags.version, (2, 3, 0))

    def test_original_jpeg_thumbnail_fallbacks_are_retained(self):
        track = self.track(artwork='https://img.youtube.com/vi/example/maxresdefault.jpg')
        responses = [HTTPError('https://img.youtube.com', 404, 'missing', {}, None),
                     HTTPError('https://img.youtube.com', 404, 'missing', {}, None),
                     io.BytesIO(cover_bytes('JPEG'))]
        with patch('ytd_core.urlopen', side_effect=responses) as request:
            data = core.fetch_artwork(track)
        self.assertTrue(data.startswith(b'\xff\xd8\xff'))
        self.assertEqual([call.args[0].full_url.rsplit('/', 1)[-1] for call in request.call_args_list],
                         ['maxresdefault.jpg', 'hqdefault.jpg', 'sddefault.jpg'])

    def test_existing_flat_song_moves_to_album_and_repairs_metadata_cover_without_audio_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / 'seether - seether - Gasoline.mp3'
            source = root / 'tone.wav'
            make_tone(source)
            core.convert(source, original)
            core.write_tags(original, self.track(title='seether - Gasoline', year='2002', genre='Rock'))
            tags = ID3(original)
            tags.add(TXXX(encoding=3, desc='REPLAYGAIN_TRACK_GAIN', text=['-3.0 dB']))
            tags.add(USLT(encoding=3, lang='eng', desc='Lyrics', text='User lyrics'))
            tags.save(original, v2_version=3)
            audio_bytes = original.read_bytes()[MP3(original).info.frame_offset:]
            with patch('ytd_core.fetch_audio') as download, patch('ytd_core.convert') as encode, \
                 patch('ytd_core.urlopen', return_value=io.BytesIO(cover_bytes('WEBP'))):
                result, message = core.download_track(self.track(artwork='https://images.example/cover.webp'), root)
                download.assert_not_called()
                encode.assert_not_called()
            self.assertEqual(result, root / 'Disclaimer' / 'Gasoline.mp3')
            self.assertFalse(original.exists())
            self.assertEqual(result.read_bytes()[MP3(result).info.frame_offset:], audio_bytes)
            tags = ID3(result)
            for key, expected in [('TIT2', 'Gasoline'), ('TPE1', 'Seether'), ('TALB', 'Disclaimer'), ('TRCK', '1')]:
                self.assertEqual(str(tags[key]), expected)
            self.assertEqual(str(tags['TXXX:REPLAYGAIN_TRACK_GAIN']), '-3.0 dB')
            self.assertEqual(tags.getall('USLT')[0].text, 'User lyrics')
            self.assertEqual(str(tags['TDRC']), '2002')
            self.assertEqual(str(tags['TCON']), 'Rock')
            self.assertEqual(tags.getall('APIC')[0].mime, 'image/jpeg')
            self.assertIn('album folder updated', message)

    def test_repair_failure_keeps_the_original_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / 'old.mp3'
            source = root / 'tone.wav'
            make_tone(source)
            core.convert(source, original)
            core.write_tags(original, self.track())
            before = original.read_bytes()
            with patch('ytd_core.write_tags', side_effect=OSError('test write failure')):
                with self.assertRaisesRegex(OSError, 'test write failure'):
                    core.download_track(self.track(), root)
            self.assertEqual(original.read_bytes(), before)
            self.assertEqual(list(root.rglob('*.mp3')), [original])

    def test_new_files_retain_encoder_and_quality_information(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tags.mp3'
            path.write_bytes(b'')
            core.write_tags(path, self.track())
            tags = ID3(path)
            self.assertEqual(str(tags['TENC']), 'libmp3lame')
            self.assertIn('V0 (VBR)', str(tags['TSSE']))

    def test_failed_cover_update_keeps_a_previous_cover(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tags.mp3'
            path.write_bytes(b'')
            with patch('ytd_core.urlopen', return_value=io.BytesIO(cover_bytes('PNG'))):
                core.write_tags(path, self.track(artwork='https://images.example/first.png'))
            previous_cover = ID3(path).getall('APIC')[0].data
            with patch('ytd_core.urlopen', side_effect=TimeoutError('network timeout')):
                warning = core.write_tags(path, self.track(artwork='https://images.example/replacement.webp'), encoded=False)
            self.assertIn('Existing cover kept', warning)
            self.assertEqual(ID3(path).getall('APIC')[0].data, previous_cover)

    def test_repair_never_overwrites_an_unrelated_song_in_album_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'tone.wav'
            make_tone(source)
            original = root / 'old.mp3'
            core.convert(source, original)
            core.write_tags(original, self.track())
            destination = root / 'Disclaimer'
            destination.mkdir()
            unrelated = destination / 'Gasoline.mp3'
            core.convert(source, unrelated)
            core.write_tags(unrelated, self.track(url='https://youtu.be/different'))
            unrelated_bytes = unrelated.read_bytes()
            result, _ = core.download_track(self.track(), root)
            self.assertEqual(result.name, 'Gasoline (2).mp3')
            self.assertEqual(unrelated.read_bytes(), unrelated_bytes)
            self.assertFalse(original.exists())

    def test_existing_optional_metadata_is_kept_unless_user_explicitly_clears_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'song.mp3'
            path.write_bytes(b'')
            core.write_tags(path, self.track(year='2002', genre='Rock'))
            retained = core.merge_existing_metadata(self.track(), path)
            self.assertEqual((retained.year, retained.genre), ('2002', 'Rock'))
            cleared = core.merge_existing_metadata(self.track(edited_fields=['year', 'genre']), path)
            self.assertEqual((cleared.year, cleared.genre), ('', ''))


if __name__ == '__main__':
    unittest.main()
