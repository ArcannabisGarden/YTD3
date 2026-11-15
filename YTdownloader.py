"""Windows desktop entry point and process-isolated operation controls."""
import multiprocessing

# Must run before GUI imports when the frozen EXE starts a background worker.
if __name__ == '__main__':
    multiprocessing.freeze_support()

from dataclasses import asdict
from pathlib import Path
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from ytd_core import Track, validate_track, validate_url, format_error, relative_output_path
from ytd_jobs import WorkerJob

APP_VERSION = '0.3.3'
FIELDS = [('title', 'Title'), ('artist', 'Artist'), ('album', 'Album'),
          ('albumartist', 'Album artist'), ('track', 'Track number'),
          ('year', 'Year'), ('genre', 'Genre'), ('artwork', 'Artwork URL')]


def settings_path():
    return Path(os.environ.get('APPDATA', str(Path.home()))) / 'YTD3' / 'settings.json'


class App:
    def __init__(self, root):
        self.root = root
        root.title(f'YTD3 {APP_VERSION} — Song downloader')
        root.geometry('1120x760')
        root.minsize(980, 700)
        self.tracks = []
        self.current = None
        self.loading_fields = False
        self.busy = False
        self.job = None
        self.kind = None
        self.close_after = False
        self.cancel_requested = False
        self.paused = False
        self.completed = set()
        self.batch = []
        self.batch_position = 0
        self.consecutive_failures = 0
        self.last_detail = ''
        self.url = tk.StringVar()
        self.folder = tk.StringVar(value=str(Path.home() / 'Music' / 'YTD3'))
        self.album_mode = tk.StringVar(value='Album')
        self.cookies_file = ''  # Session files are never remembered in settings.
        self.session_label = tk.StringVar(value='No session file selected')
        self.output_preview = tk.StringVar(value='Select a song to see its output name.')
        self.status = tk.StringVar(value='Paste a link to preview songs. Playlists use album folders and track order by default.')
        self.values = {key: tk.StringVar() for key, _ in FIELDS}
        try:
            saved = json.loads(settings_path().read_text(encoding='utf-8'))
            if isinstance(saved.get('folder'), str):
                self.folder.set(saved['folder'])
        except (OSError, ValueError, AttributeError):
            pass
        self.build()
        for variable in self.values.values():
            variable.trace_add('write', self.edit)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.timer = root.after(100, self.poll)

    def build(self):
        style = ttk.Style()
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        panel = ttk.Frame(self.root, padding=16)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='YTD3', font=('Segoe UI', 24, 'bold')).pack(anchor='w')
        ttk.Label(panel, text='Preview songs, edit their details, and save as MP3.').pack(anchor='w', pady=(0, 12))
        link_row = ttk.Frame(panel)
        link_row.pack(fill='x')
        self.url_entry = ttk.Entry(link_row, textvariable=self.url)
        self.url_entry.pack(side='left', fill='x', expand=True)
        self.preview_button = ttk.Button(link_row, text='Preview link', command=self.load)
        self.preview_button.pack(side='left', padx=(8, 0))
        mode_row = ttk.Frame(panel)
        mode_row.pack(fill='x', pady=8)
        ttk.Label(mode_row, text='Playlist type:').pack(side='left', padx=(0, 8))
        self.mode_picker = ttk.Combobox(mode_row, state='readonly', width=17,
            textvariable=self.album_mode, values=['Auto', 'Album', 'Mixed playlist'])
        self.mode_picker.pack(side='left')
        ttk.Label(mode_row, text='Album uses the playlist name and track order. Choose Mixed playlist for collections.').pack(side='left', padx=10)
        session = ttk.Frame(panel)
        session.pack(fill='x', pady=(0, 10))
        ttk.Label(session, text='YouTube session (optional):').pack(side='left')
        self.session_button = ttk.Button(session, text='Load cookies.txt…', command=self.browse_session)
        self.session_button.pack(side='left', padx=8)
        self.clear_session_button = ttk.Button(session, text='Clear', command=self.clear_session)
        self.clear_session_button.pack(side='left')
        ttk.Label(session, textvariable=self.session_label).pack(side='left', padx=10)
        middle = ttk.Frame(panel)
        middle.pack(fill='both', expand=True)
        left = ttk.Frame(middle)
        left.pack(side='left', fill='both', expand=True, padx=(0, 16))
        self.tree = ttk.Treeview(left, columns=('artist', 'album', 'track', 'state'), selectmode='browse', height=8)
        for key, label, width in [('#0', 'Song', 190), ('artist', 'Artist', 120),
                                   ('album', 'Album', 120), ('track', '#', 38), ('state', 'Status', 95)]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=30, stretch=key not in ('track', 'state'))
        scrollbar = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        right = ttk.Frame(middle)
        right.pack(side='left', fill='both')
        self.entries = []
        for row, (key, label) in enumerate(FIELDS):
            ttk.Label(right, text=label).grid(row=row * 2, column=0, sticky='w', pady=(3, 0))
            entry = ttk.Entry(right, textvariable=self.values[key], width=34, state='disabled')
            entry.grid(row=row * 2 + 1, column=0, sticky='ew')
            self.entries.append(entry)
        self.art_button = ttk.Button(right, text='Open artwork preview', command=self.show_artwork, state='disabled')
        self.art_button.grid(row=16, column=0, sticky='w', pady=6)
        ttk.Label(panel, text='Songs with an album are saved in an album subfolder. Existing app downloads can have their tags and artwork updated.').pack(anchor='w', pady=(10, 6))
        output = ttk.Frame(panel)
        output.pack(fill='x')
        ttk.Label(output, text='Save to:').pack(side='left', padx=(0, 8))
        self.folder_entry = ttk.Entry(output, textvariable=self.folder)
        self.folder_entry.pack(side='left', fill='x', expand=True)
        self.browse_button = ttk.Button(output, text='Browse…', command=self.browse)
        self.browse_button.pack(side='left', padx=8)
        self.download_button = ttk.Button(output, text='Download / update songs', command=self.download, state='disabled')
        self.download_button.pack(side='left')
        controls = ttk.Frame(panel)
        controls.pack(fill='x', pady=(10, 4))
        self.pause_button = ttk.Button(controls, text='Pause', command=self.toggle_pause, state='disabled')
        self.pause_button.pack(side='left')
        self.cancel_button = ttk.Button(controls, text='Cancel', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=8)
        ttk.Label(controls, textvariable=self.output_preview, wraplength=570).pack(side='left', padx=10)
        ttk.Button(controls, text='Save log…', command=self.save_log).pack(side='right')
        self.progress = ttk.Progressbar(panel, maximum=100)
        self.progress.pack(fill='x', pady=(6, 6))
        ttk.Label(panel, textvariable=self.status, wraplength=1040).pack(anchor='w')
        self.log = tk.Text(panel, height=4, wrap='word', state='disabled', font=('Segoe UI', 9))
        self.log.pack(fill='x', pady=(6, 0))

    def update_row(self, index, state=None):
        track = self.tracks[index]
        old = self.tree.item(str(index), 'values')
        state = state if state is not None else (old[3] if old else 'Ready')
        self.tree.item(str(index), text=track.title, values=(track.artist, track.album, track.track, state))

    def edit(self, *_):
        if self.loading_fields or self.current is None or self.busy:
            return
        track = self.tracks[self.current]
        for key, _ in FIELDS:
            value = self.values[key].get().strip()
            if value != getattr(track, key) and key not in track.edited_fields:
                track.edited_fields.append(key)
            setattr(track, key, value)
        self.update_row(self.current)
        self.update_output_preview()

    def update_output_preview(self):
        if self.current is None:
            self.output_preview.set('Select a song to see its output name.')
        else:
            self.output_preview.set('Output: ' + relative_output_path(self.tracks[self.current]).as_posix())

    def select(self, _=None):
        selected = self.tree.selection()
        if not selected or int(selected[0]) >= len(self.tracks):
            return
        self.current = int(selected[0])
        self.loading_fields = True
        for key, _ in FIELDS:
            self.values[key].set(getattr(self.tracks[self.current], key))
        self.loading_fields = False
        self.update_output_preview()
        for entry in self.entries:
            entry.configure(state='disabled' if self.busy else 'normal')
        self.art_button.configure(state='disabled' if self.busy else 'normal')

    def show_artwork(self):
        from urllib.parse import urlparse
        url = self.values['artwork'].get().strip()
        if urlparse(url).scheme in ('https', 'http'):
            webbrowser.open(url)
        else:
            messagebox.showinfo('Artwork', 'Enter an HTTP(S) artwork image URL first.')

    def browse(self):
        folder = filedialog.askdirectory(title='Choose where to save MP3 files')
        if folder:
            self.folder.set(folder)

    def browse_session(self):
        path = filedialog.askopenfilename(title='Select a local YouTube cookies.txt file',
                                         filetypes=[('Cookies files', '*.txt'), ('All files', '*.*')])
        if path:
            self.cookies_file = path
            self.session_label.set(Path(path).name + ' (this session only)')

    def clear_session(self):
        self.cookies_file = ''
        self.session_label.set('No session file selected')

    def save_log(self):
        path = filedialog.asksaveasfilename(title='Save download log', defaultextension='.txt',
                                          initialfile='YTD3-log.txt', filetypes=[('Text file', '*.txt')])
        if path:
            try:
                names = [{'video_id': track.video_id, 'title': track.title, 'artist': track.artist,
                          'album': track.album, 'output': relative_output_path(track).as_posix()}
                         for track in self.tracks]
                Path(path).write_text(f'YTD3 {APP_VERSION}\n' + self.log.get('1.0', 'end')
                    + '\nSong names and output files:\n' + json.dumps(names, indent=2, ensure_ascii=False), encoding='utf-8')
            except OSError as exc:
                messagebox.showerror('Could not save log', str(exc))

    def set_busy(self, value):
        self.busy = value
        self.paused = False
        for widget in (self.preview_button, self.url_entry, self.folder_entry, self.browse_button,
                       self.session_button, self.clear_session_button):
            widget.configure(state='disabled' if value else 'normal')
        self.mode_picker.configure(state='disabled' if value else 'readonly')
        pending = len(self.completed) < len(self.tracks)
        self.download_button.configure(state='normal' if self.tracks and pending and not value else 'disabled',
            text='Retry unfinished songs' if self.completed or any(self.tree.set(str(i), 'state') in ('Failed', 'Needs sign-in') for i in range(len(self.tracks))) else 'Download / update songs')
        for entry in self.entries:
            entry.configure(state='normal' if self.current is not None and not value else 'disabled')
        self.art_button.configure(state='normal' if self.current is not None and not value else 'disabled')
        self.pause_button.configure(text='Pause', state='normal' if value else 'disabled')
        self.cancel_button.configure(state='normal' if value else 'disabled')

    def load(self):
        url = self.url.get().strip()
        try:
            validate_url(url)
        except ValueError as exc:
            messagebox.showinfo('YouTube link', str(exc))
            return
        self.current = None
        self.update_output_preview()
        self.tracks = []
        self.completed.clear()
        self.tree.delete(*self.tree.get_children())
        self.loading_fields = True
        for variable in self.values.values():
            variable.set('')
        self.loading_fields = False
        self.cancel_requested = False
        self.kind = 'preview'
        self.set_busy(True)
        self.progress.configure(mode='indeterminate')
        self.progress.start()
        self.last_detail = 'Loading song details…'
        self.status.set(self.last_detail)
        self.append_log(f'Preview: {url} — playlist type: {self.album_mode.get()}')
        try:
            self.job = WorkerJob('preview', {'url': url, 'album_mode': self.album_mode.get(),
                                           'cookies_file': self.cookies_file})
        except Exception as exc:
            self.finish_preview(error=format_error(exc))

    def download(self):
        self.batch = [index for index in range(len(self.tracks)) if index not in self.completed]
        if not self.batch:
            return
        try:
            for index in self.batch:
                validate_track(self.tracks[index])
            if not self.folder.get().strip():
                raise ValueError('Choose a destination folder.')
            Path(self.folder.get().strip()).mkdir(parents=True, exist_ok=True)
        except (ValueError, OSError) as exc:
            messagebox.showerror('Check song details', str(exc))
            return
        self.kind = 'download'
        self.cancel_requested = False
        self.batch_position = 0
        self.consecutive_failures = 0
        self.set_busy(True)
        self.progress.configure(mode='determinate', value=0)
        self.append_log(f'Starting {len(self.batch)} unfinished song(s). Already saved: {len(self.completed)}.')
        try:
            path = settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'folder': self.folder.get().strip()}), encoding='utf-8')
        except OSError:
            self.append_log('Could not remember the output folder for next time.')
        self.start_next()

    def start_next(self):
        if self.cancel_requested:
            self.finish_download('Cancelled')
            return
        if self.batch_position >= len(self.batch):
            self.finish_download('Finished')
            return
        if self.paused:
            self.status.set('Paused between songs. Resume to continue, or Cancel to stop.')
            return
        index = self.batch[self.batch_position]
        self.update_row(index, 'Downloading')
        self.tree.see(str(index))
        self.progress.configure(value=0)
        self.last_detail = f'{self.batch_position + 1}/{len(self.batch)}: {self.tracks[index].title} — starting…'
        self.status.set(self.last_detail)
        try:
            self.job = WorkerJob('download', {'track': asdict(self.tracks[index]),
                'output': self.folder.get().strip(), 'cookies_file': self.cookies_file})
        except Exception as exc:
            self.update_row(index, 'Failed')
            self.append_log(format_error(exc))
            self.finish_download('Stopped — could not start download')

    def toggle_pause(self):
        if not self.busy or self.cancel_requested:
            return
        try:
            if self.paused:
                if self.job:
                    self.job.resume()
                self.paused = False
                self.pause_button.configure(text='Pause')
                self.status.set(self.last_detail)
                if not self.job and self.kind == 'download':
                    self.start_next()
            else:
                if self.job:
                    self.job.pause()
                self.paused = self.job.paused if self.job else True
                if self.paused:
                    self.pause_button.configure(text='Resume')
                    self.status.set('Paused. Resume to continue, or Cancel to stop and keep completed songs.')
        except Exception as exc:
            self.append_log(f'Could not change pause state: {format_error(exc)}')
            messagebox.showerror('Pause / Resume', format_error(exc))

    def cancel(self):
        self.cancel_requested = True
        self.status.set('Cancelling and cleaning temporary files… Completed songs will be kept.')
        self.pause_button.configure(state='disabled')
        self.cancel_button.configure(state='disabled')
        if self.job:
            try:
                self.job.cancel()
            except Exception as exc:
                self.append_log(f'Could not stop worker: {format_error(exc)}')
                self.cancel_button.configure(state='normal')
        elif self.kind == 'preview':
            self.finish_preview(cancelled=True)
        else:
            self.finish_download('Cancelled')

    def close_job(self):
        job, self.job = self.job, None
        if job:
            warning = job.close()
            if warning:
                self.append_log(warning)

    def finish_preview(self, tracks=None, error=None, cancelled=False):
        self.close_job()
        self.progress.stop()
        self.progress.configure(mode='determinate', value=0)
        if tracks and not cancelled:
            self.tracks = [Track(**track) for track in tracks]
            for index, track in enumerate(self.tracks):
                self.tree.insert('', 'end', iid=str(index), text=track.title,
                                 values=(track.artist, track.album, track.track, 'Ready'))
            self.tree.selection_set('0')
            self.select()
            self.last_detail = f'{len(tracks)} song(s) loaded. Review the album and track columns, then download.'
        elif error:
            self.last_detail = 'Preview failed. See the log for the full reason.'
            self.append_log(error)
            if not self.close_after:
                messagebox.showerror('Could not load songs', error)
        else:
            self.last_detail = 'Preview cancelled.'
        self.set_busy(False)
        self.status.set(self.last_detail)

    def finish_download(self, reason):
        self.close_job()
        self.set_busy(False)
        remaining = len(self.tracks) - len(self.completed)
        self.status.set(f'{reason}. {len(self.completed)} song(s) saved; {remaining} unfinished. See the log for details.')
        self.append_log(self.status.get())
        self.progress.configure(value=100 if remaining == 0 else 0)

    def append_log(self, message):
        self.log.configure(state='normal')
        self.log.insert('end', message + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def handle_result(self, value):
        if self.kind == 'preview':
            self.finish_preview(tracks=value, cancelled=self.cancel_requested)
            return
        index = self.batch[self.batch_position]
        self.completed.add(index)
        self.update_row(index, 'Saved')
        self.append_log(f'Saved: {value["path"]}')
        if value.get('tags'):
            tags = value['tags']
            self.append_log(f'Verified tags: Title={tags["title"]!r}; Artist={tags["artist"]!r}; Album={tags["album"]!r}')
        if value.get('warning'):
            self.append_log(value['warning'])
        self.consecutive_failures = 0
        self.close_job()
        self.batch_position += 1
        self.start_next()

    def handle_error(self, value):
        if self.kind == 'preview':
            self.finish_preview(error=value['message'], cancelled=self.cancel_requested)
            return
        index = self.batch[self.batch_position]
        self.update_row(index, 'Needs sign-in' if value.get('needs_sign_in') else 'Failed')
        self.append_log(f'Skipped: {self.tracks[index].title}: {value["message"]}' if value.get('video_only')
                        else f'Failed: {self.tracks[index].title}: {value["message"]}')
        self.consecutive_failures = 0 if value.get('video_only') else self.consecutive_failures + 1
        self.close_job()
        self.batch_position += 1
        if value.get('stop_batch') or self.consecutive_failures >= 2:
            self.finish_download('Stopped after download errors — retry unfinished songs when resolved')
        else:
            self.start_next()

    def poll(self):
        job = self.job
        if job:
            terminal = False
            for kind, value in job.drain():
                if kind == 'warning':
                    self.append_log(value)
                elif kind == 'status':
                    self.last_detail = (f'{self.batch_position + 1}/{len(self.batch)}: ' if self.kind == 'download' else '') + value
                    if not self.paused and not self.cancel_requested:
                        self.status.set(self.last_detail)
                elif kind == 'progress' and not self.cancel_requested:
                    self.progress.configure(value=value)
                elif kind == 'result':
                    terminal = True
                    self.handle_result(value)
                    break
                elif kind == 'error' and not self.cancel_requested:
                    terminal = True
                    self.handle_error(value)
                    break
            if not terminal and self.job is job and not job.alive:
                job.exit_polls += 1
                if self.cancel_requested:
                    if self.kind == 'preview':
                        self.finish_preview(cancelled=True)
                    else:
                        self.update_row(self.batch[self.batch_position], 'Cancelled')
                        self.finish_download('Cancelled')
                elif job.exit_polls > 2:
                    self.handle_error({'message': f'The background worker exited unexpectedly (code {job.process.exitcode}).', 'stop_batch': True})
        if self.close_after and not self.busy:
            self.destroy()
            return
        self.timer = self.root.after(100, self.poll)

    def destroy(self):
        if self.timer:
            self.root.after_cancel(self.timer)
        self.root.destroy()

    def close(self):
        if self.busy:
            if messagebox.askyesno('Download in progress', 'Cancel the current process and close? Completed songs will be kept.'):
                self.close_after = True
                self.cancel()
        else:
            self.destroy()


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        from ytd_smoke import run_self_test
        raise SystemExit(run_self_test(sys.argv[2]))
    root = tk.Tk()
    App(root)
    root.mainloop()
