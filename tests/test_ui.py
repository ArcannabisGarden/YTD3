from dataclasses import asdict
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from YTdownloader import App
from ytd_core import Track


class FakeJob:
    jobs = []

    def __init__(self, kind, payload):
        self.kind = kind
        self.payload = payload
        self.events = []
        self.alive = True
        self.paused = False
        self.cancelled = False
        self.exit_polls = 0
        self.process = SimpleNamespace(exitcode=0)
        self.jobs.append(self)

    def drain(self):
        messages, self.events = self.events, []
        return messages

    def close(self):
        self.alive = False
        return ''

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def cancel(self):
        self.cancelled = True
        self.alive = False


class DesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Display unavailable: {exc}')
        self.root.withdraw()
        FakeJob.jobs = []
        self.factory_patch = patch('YTdownloader.WorkerJob', FakeJob)
        self.factory_patch.start()
        self.temporary = tempfile.TemporaryDirectory()
        self.settings_patch = patch('YTdownloader.settings_path', return_value=Path(self.temporary.name) / 'settings.json')
        self.settings_patch.start()
        self.app = App(self.root)
        self.app.folder.set(self.temporary.name)

    def tearDown(self):
        if hasattr(self, 'root'):
            for callback in self.root.tk.call('after', 'info'):
                self.root.after_cancel(callback)
            self.root.destroy()
            self.factory_patch.stop()
            self.settings_patch.stop()
            self.temporary.cleanup()

    def load_preview(self):
        tracks = [Track('https://youtu.be/a', 'a', 'First', 'Artist', album='Album', track='1'),
                  Track('https://youtu.be/b', 'b', 'Second', 'Artist', album='Album', track='2')]
        self.app.url.set('https://youtube.com/playlist?list=OLAK5uy_example')
        self.app.load()
        self.assertEqual(self.app.job.payload['album_mode'], 'Album')
        self.app.job.events.append(('result', [asdict(track) for track in tracks]))
        self.app.poll()
        self.root.update()

    def test_metadata_visible_and_edits_survive_selection(self):
        self.load_preview()
        self.assertEqual(self.app.tree.set('0', 'album'), 'Album')
        self.assertEqual(self.app.tree.set('1', 'track'), '2')
        self.app.values['title'].set('Edited title (Live)')
        self.app.values['album'].set('My Album')
        self.app.tree.selection_set('1')
        self.root.update()
        self.assertEqual(self.app.values['title'].get(), 'Second')
        self.app.tree.selection_set('0')
        self.root.update()
        self.assertEqual(self.app.values['title'].get(), 'Edited title (Live)')
        self.assertEqual(self.app.values['album'].get(), 'My Album')

    def test_preview_pause_resume_and_cancel(self):
        self.app.url.set('https://youtu.be/a')
        self.app.load()
        job = self.app.job
        self.app.toggle_pause()
        self.assertTrue(job.paused)
        self.assertEqual(self.app.pause_button['text'], 'Resume')
        job.events.append(('status', 'New incoming worker status'))
        self.app.poll()
        self.assertIn('Paused', self.app.status.get())
        self.app.toggle_pause()
        self.assertFalse(job.paused)
        self.app.toggle_pause()
        self.app.cancel()
        self.app.poll()
        self.assertTrue(job.cancelled)
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.tracks, [])
        self.assertEqual(str(self.app.pause_button['state']), 'disabled')

    def test_validation_blocks_worker(self):
        self.load_preview()
        self.app.values['year'].set('invalid')
        count = len(FakeJob.jobs)
        with patch('YTdownloader.messagebox.showerror') as error:
            self.app.download()
        error.assert_called_once()
        self.assertEqual(len(FakeJob.jobs), count)

    def test_failed_new_preview_clears_previous_songs(self):
        self.load_preview()
        self.app.url.set('https://youtu.be/new')
        self.app.load()
        self.app.job.events.append(('error', {'message': 'YouTube needs sign-in', 'stop_batch': True}))
        with patch('YTdownloader.messagebox.showerror'):
            self.app.poll()
        self.assertEqual(self.app.tracks, [])
        self.assertEqual(self.app.values['title'].get(), '')
        self.assertEqual(str(self.app.download_button['state']), 'disabled')
        self.assertIn('YouTube needs sign-in', self.app.log.get('1.0', 'end'))

    def test_shared_stream_failure_stops_batch_and_allows_retry(self):
        self.load_preview()
        self.app.download()
        before = len(FakeJob.jobs)
        self.app.job.events.append(('error', {'message': 'SABR PoToken PENDING', 'stop_batch': True}))
        self.app.poll()
        self.assertEqual(len(FakeJob.jobs), before, 'must not start the next song after a shared failure')
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.tree.set('0', 'state'), 'Failed')
        self.assertEqual(self.app.download_button['text'], 'Retry unfinished songs')
        self.assertIn('SABR PoToken PENDING', self.app.log.get('1.0', 'end'))

    def test_cancel_preserves_completed_and_retry_only_downloads_unfinished(self):
        self.load_preview()
        self.app.download()
        self.assertEqual(str(self.app.entries[0]['state']), 'disabled')
        self.app.job.events.append(('result', {'path': 'first.mp3', 'warning': ''}))
        self.app.poll()
        self.assertEqual(self.app.completed, {0})
        self.assertEqual(self.app.job.payload['track']['video_id'], 'b')
        second = self.app.job
        self.app.toggle_pause()
        self.app.cancel()
        self.app.poll()
        self.assertTrue(second.cancelled)
        self.assertEqual(self.app.tree.set('0', 'state'), 'Saved')
        self.assertEqual(self.app.tree.set('1', 'state'), 'Cancelled')
        self.assertIn('1 song(s) saved; 1 unfinished', self.app.status.get())
        self.assertEqual(str(self.app.entries[0]['state']), 'normal')
        self.app.download()
        self.assertEqual(self.app.job.payload['track']['video_id'], 'b')
        self.app.job.events.append(('result', {'path': 'second.mp3', 'warning': ''}))
        self.app.poll()
        self.assertEqual(self.app.completed, {0, 1})
        self.assertFalse(self.app.busy)
        self.assertEqual(str(self.app.download_button['state']), 'disabled')

    def test_close_cancels_work_and_keeps_saved_files(self):
        self.load_preview()
        self.app.download()
        job = self.app.job
        with patch('YTdownloader.messagebox.askyesno', return_value=True):
            self.app.close()
        self.assertTrue(self.app.close_after)
        self.assertTrue(job.cancelled)
        # Do not destroy the test's root; tearDown owns it.
        self.app.close_after = False
        self.app.poll()
        self.assertFalse(self.app.busy)

    def test_session_file_is_not_saved_to_settings(self):
        self.load_preview()
        self.app.cookies_file = 'local-session.txt'
        self.app.download()
        self.assertEqual(self.app.job.payload['cookies_file'], 'local-session.txt')
        self.assertNotIn('session', (Path(self.temporary.name) / 'settings.json').read_text())
        self.assertNotIn('cookies', (Path(self.temporary.name) / 'settings.json').read_text())

    def test_pause_at_song_boundary_does_not_start_next_song(self):
        self.load_preview()
        self.app.download()
        self.app.job.events.append(('result', {'path': 'first.mp3', 'warning': ''}))
        count = len(FakeJob.jobs)
        self.app.toggle_pause()
        self.app.poll()
        self.assertEqual(self.app.completed, {0})
        self.assertIsNone(self.app.job)
        self.assertTrue(self.app.busy)
        self.assertEqual(len(FakeJob.jobs), count)
        self.app.toggle_pause()
        self.assertEqual(self.app.job.payload['track']['video_id'], 'b')

    def test_two_age_restricted_songs_do_not_stop_other_downloads(self):
        self.load_preview()
        third = Track('https://youtu.be/c', 'c', 'Third', 'Artist', album='Album', track='3')
        self.app.tracks.append(third)
        self.app.tree.insert('', 'end', iid='2', text=third.title,
                             values=(third.artist, third.album, third.track, 'Ready'))
        self.app.download()
        error = {'message': 'This song needs YouTube age verification.',
                 'stop_batch': False, 'video_only': True, 'needs_sign_in': True}
        for index in (0, 1):
            self.app.job.events.append(('error', error))
            self.app.poll()
            self.assertEqual(self.app.tree.set(str(index), 'state'), 'Needs sign-in')
            self.assertTrue(self.app.busy)
        self.assertEqual(self.app.job.payload['track']['video_id'], 'c')
        self.app.job.events.append(('result', {'path': 'third.mp3', 'warning': ''}))
        self.app.poll()
        self.assertEqual(self.app.completed, {2})
        self.assertFalse(self.app.busy)
        self.app.download()
        self.assertEqual(self.app.batch, [0, 1])

    def test_output_preview_tracks_title_changes_without_artist_prefix(self):
        self.load_preview()
        self.app.values['artist'].set('Seether')
        self.app.values['title'].set('Gasoline')
        self.app.values['album'].set('Disclaimer II')
        self.assertEqual(self.app.output_preview.get(), 'Output: Disclaimer II/Gasoline.mp3')
        self.app.tree.selection_set('1')
        self.root.update()
        self.assertEqual(self.app.output_preview.get(), 'Output: Album/Second.mp3')

    def test_saved_log_includes_actual_tags_and_filename_preview(self):
        self.load_preview()
        self.app.cookies_file = 'private-session.txt'
        self.app.download()
        self.app.job.events.append(('result', {'path': 'First.mp3', 'warning': '',
            'tags': {'title': 'First', 'artist': 'Artist', 'album': 'Album', 'track': '1'}}))
        self.app.poll()
        self.assertIn("Verified tags: Title='First'; Artist='Artist'; Album='Album'", self.app.log.get('1.0', 'end'))
        destination = Path(self.temporary.name) / 'log.txt'
        with patch('YTdownloader.filedialog.asksaveasfilename', return_value=str(destination)):
            self.app.save_log()
        contents = destination.read_text(encoding='utf-8')
        self.assertIn('Album/First.mp3', contents)
        self.assertIn('Verified tags', contents)
        self.assertNotIn('private-session.txt', contents)
