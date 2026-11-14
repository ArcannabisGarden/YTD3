"""UI checks run on Windows CI; skipped when no display is available."""
import tkinter as tk
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from YTdownloader import App
from ytd_core import Track


class DesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Display unavailable: {exc}')
        self.root.withdraw()
        self.app = App(self.root)

    def tearDown(self):
        if hasattr(self, 'root'):
            for callback in self.root.tk.call('after', 'info'):
                self.root.after_cancel(callback)
            self.root.destroy()

    def load_preview(self):
        tracks = [Track('https://youtu.be/a', 'a', 'First', 'Artist'),
                  Track('https://youtu.be/b', 'b', 'Second', 'Other')]
        self.app.events.put(('preview', tracks))
        self.app.poll()
        self.root.update()

    def test_edits_survive_song_selection(self):
        self.load_preview()
        self.app.values['title'].set('Edited title (Live)')
        self.app.values['album'].set('My Album')
        self.app.tree.selection_set('1')
        self.root.update()
        self.assertEqual(self.app.values['title'].get(), 'Second')
        self.app.tree.selection_set('0')
        self.root.update()
        self.assertEqual(self.app.values['title'].get(), 'Edited title (Live)')
        self.assertEqual(self.app.values['album'].get(), 'My Album')

    def test_busy_disables_edits_and_done_restores_them(self):
        self.load_preview()
        self.app.set_busy(True)
        self.assertEqual(str(self.app.download_button['state']), 'disabled')
        self.assertEqual(str(self.app.entries[0]['state']), 'disabled')
        self.app.events.put(('done', 'Finished: 2 saved, 0 failed.'))
        self.app.poll()
        self.assertFalse(self.app.busy)
        self.assertEqual(str(self.app.entries[0]['state']), 'normal')
        self.assertEqual(str(self.app.download_button['state']), 'normal')

    def test_validation_blocks_worker(self):
        self.load_preview()
        self.app.values['year'].set('invalid')
        with patch('YTdownloader.messagebox.showerror') as error, \
             patch('YTdownloader.threading.Thread') as worker:
            self.app.download()
        error.assert_called_once()
        worker.assert_not_called()

    def test_failed_new_preview_clears_previous_songs(self):
        from pytubefix.exceptions import BotDetection
        self.load_preview()
        self.app.url.set('https://youtu.be/new')
        with patch('YTdownloader.preview', side_effect=BotDetection('new')), \
             patch('YTdownloader.threading.Thread', side_effect=lambda target, **_: SimpleNamespace(start=target)), \
             patch('YTdownloader.messagebox.showerror') as error:
            self.app.load()
            self.app.poll()
        self.assertEqual(self.app.tracks, [])
        self.assertEqual(self.app.values['title'].get(), '')
        self.assertEqual(str(self.app.download_button['state']), 'disabled')
        self.assertIn('YouTube is asking for verification', self.app.status.get())
        error.assert_called_once()

    def test_bot_block_stops_playlist_without_retrying_other_songs(self):
        from pytubefix.exceptions import BotDetection
        self.load_preview()
        with tempfile.TemporaryDirectory() as folder:
            self.app.folder.set(folder)
            with patch('YTdownloader.download_track', side_effect=BotDetection('a')) as download, \
                 patch('YTdownloader.settings_path', return_value=Path(folder) / 'settings.json'), \
                 patch('YTdownloader.threading.Thread', side_effect=lambda target, **_: SimpleNamespace(start=target)):
                self.app.download()
                self.app.poll()
        download.assert_called_once()
        self.assertIn('0 saved, 1 failed, 1 not attempted', self.app.status.get())
        self.assertIn('Stopped after YouTube requested verification', self.app.log.get('1.0', 'end'))
