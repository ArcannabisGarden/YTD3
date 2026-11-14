"""Windows desktop entry point. Run with Python or build with build_windows.bat."""
from copy import deepcopy
from pathlib import Path
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from ytd_core import preview, download_track, validate_track

FIELDS = [('title', 'Title'), ('artist', 'Artist'), ('album', 'Album'),
          ('albumartist', 'Album artist'), ('track', 'Track number'),
          ('year', 'Year'), ('genre', 'Genre'), ('artwork', 'Artwork URL')]


def settings_path():
    return Path(os.environ.get('APPDATA', str(Path.home()))) / 'YTD3' / 'settings.json'


class App:
    def __init__(self, root):
        self.root = root
        self.root.title('YTD3 — Song downloader')
        self.root.geometry('1040x750')
        self.root.minsize(850, 650)
        self.events = queue.Queue()
        self.tracks = []
        self.current = None
        self.busy = False
        self.loading_fields = False
        self.close_after = False
        self.url = tk.StringVar()
        self.folder = tk.StringVar(value=str(Path.home() / 'Music' / 'YTD3'))
        self.album_mode = tk.BooleanVar()
        self.status = tk.StringVar(value='Paste a link, then preview and edit its song details.')
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
        root.after(100, self.poll)

    def build(self):
        style = ttk.Style()
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        panel = ttk.Frame(self.root, padding=18)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='YTD3', font=('Segoe UI', 24, 'bold')).pack(anchor='w')
        ttk.Label(panel, text='Preview your songs. Make the details yours. Save as MP3.').pack(anchor='w', pady=(0, 14))
        link_row = ttk.Frame(panel)
        link_row.pack(fill='x')
        self.url_entry = ttk.Entry(link_row, textvariable=self.url)
        self.url_entry.pack(side='left', fill='x', expand=True)
        self.preview_button = ttk.Button(link_row, text='Preview link', command=self.load)
        self.preview_button.pack(side='left', padx=(8, 0))
        self.mode_check = ttk.Checkbutton(panel, text='Treat playlist as an album (use playlist title and track order)', variable=self.album_mode)
        self.mode_check.pack(anchor='w', pady=8)
        middle = ttk.Frame(panel)
        middle.pack(fill='both', expand=True)
        left = ttk.Frame(middle)
        left.pack(side='left', fill='both', expand=True, padx=(0, 16))
        self.tree = ttk.Treeview(left, columns=('artist',), selectmode='browse', height=10)
        self.tree.heading('#0', text='Song')
        self.tree.heading('artist', text='Artist')
        self.tree.column('#0', width=235, minwidth=120)
        self.tree.column('artist', width=140, minwidth=90)
        scrollbar = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        right = ttk.Frame(middle)
        right.pack(side='left', fill='both')
        self.entries = []
        for row, (key, label) in enumerate(FIELDS):
            ttk.Label(right, text=label).grid(row=row * 2, column=0, sticky='w', pady=(4, 0))
            entry = ttk.Entry(right, textvariable=self.values[key], width=39, state='disabled')
            entry.grid(row=row * 2 + 1, column=0, sticky='ew')
            self.entries.append(entry)
        self.art_button = ttk.Button(right, text='Open artwork preview', command=self.show_artwork, state='disabled')
        self.art_button.grid(row=16, column=0, sticky='w', pady=8)
        ttk.Label(panel, text='Automatic details are guesses. Keep Live/Remix labels and correct uploader names as needed.').pack(anchor='w', pady=(10, 8))
        output = ttk.Frame(panel)
        output.pack(fill='x')
        ttk.Label(output, text='Save to:').pack(side='left', padx=(0, 8))
        self.folder_entry = ttk.Entry(output, textvariable=self.folder)
        self.folder_entry.pack(side='left', fill='x', expand=True)
        self.browse_button = ttk.Button(output, text='Browse…', command=self.browse)
        self.browse_button.pack(side='left', padx=8)
        self.download_button = ttk.Button(output, text='Download all songs', command=self.download, state='disabled')
        self.download_button.pack(side='left')
        self.progress = ttk.Progressbar(panel, maximum=100)
        self.progress.pack(fill='x', pady=(14, 6))
        ttk.Label(panel, textvariable=self.status, wraplength=960).pack(anchor='w')
        self.log = tk.Text(panel, height=4, wrap='word', state='disabled', font=('Segoe UI', 9))
        self.log.pack(fill='x', pady=(6, 0))

    def edit(self, *_):
        if self.loading_fields or self.current is None or self.busy:
            return
        track = self.tracks[self.current]
        for key, _ in FIELDS:
            setattr(track, key, self.values[key].get().strip())
        self.tree.item(str(self.current), text=track.title, values=(track.artist,))

    def select(self, _=None):
        selected = self.tree.selection()
        if not selected:
            return
        self.current = int(selected[0])
        self.loading_fields = True
        for key, _ in FIELDS:
            self.values[key].set(getattr(self.tracks[self.current], key))
        self.loading_fields = False
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

    def set_busy(self, value):
        self.busy = value
        for widget in (self.preview_button, self.url_entry, self.mode_check,
                       self.folder_entry, self.browse_button):
            widget.configure(state='disabled' if value else 'normal')
        self.download_button.configure(state='normal' if self.tracks and not value else 'disabled')
        for entry in self.entries:
            entry.configure(state='normal' if self.current is not None and not value else 'disabled')
        self.art_button.configure(state='normal' if self.current is not None and not value else 'disabled')

    def load(self):
        url = self.url.get().strip()
        if not url:
            messagebox.showinfo('YouTube link', 'Paste a video or playlist URL first.')
            return
        album_mode = self.album_mode.get()
        self.set_busy(True)
        self.progress.configure(mode='indeterminate')
        self.progress.start()
        self.status.set('Loading song details… Large playlists can take a while.')

        def worker():
            try:
                self.events.put(('preview', preview(url, album_mode)))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def download(self):
        try:
            for track in self.tracks:
                validate_track(track)
            if not self.folder.get().strip():
                raise ValueError('Choose a destination folder.')
        except ValueError as exc:
            messagebox.showerror('Check song details', str(exc))
            return
        tracks = deepcopy(self.tracks)
        folder = self.folder.get().strip()
        self.set_busy(True)
        self.progress.configure(value=0)
        self.append_log('Starting download…')
        try:
            path = settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'folder': folder}), encoding='utf-8')
        except OSError:
            self.append_log('Could not remember the output folder for next time.')

        def worker():
            completed = 0
            for index, track in enumerate(tracks, 1):
                self.events.put(('status', f'{index}/{len(tracks)}: {track.title} — downloading, then converting and tagging…'))
                try:
                    path, warning = download_track(track, folder, lambda p: self.events.put(('progress', p)))
                    completed += 1
                    self.events.put(('log', f'Saved: {path}'))
                    if warning:
                        self.events.put(('log', warning))
                except Exception as exc:
                    self.events.put(('log', f'Failed: {track.title}: {exc}'))
            self.events.put(('done', f'Finished: {completed} saved, {len(tracks) - completed} failed. See the log for details.'))
        threading.Thread(target=worker, daemon=True).start()

    def append_log(self, message):
        self.log.configure(state='normal')
        self.log.insert('end', message + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == 'preview':
                    self.progress.stop()
                    self.progress.configure(mode='determinate', value=0)
                    self.tracks = data
                    self.current = None
                    self.tree.delete(*self.tree.get_children())
                    for index, track in enumerate(data):
                        self.tree.insert('', 'end', iid=str(index), text=track.title, values=(track.artist,))
                    self.set_busy(False)
                    self.tree.selection_set('0')
                    self.status.set(f'{len(data)} song(s) loaded. Select each song to review its details.')
                elif kind == 'error':
                    self.progress.stop()
                    self.progress.configure(mode='determinate', value=0)
                    self.set_busy(False)
                    self.status.set('Could not load this link. Check the URL and your connection, then retry.')
                    messagebox.showerror('Preview failed', data)
                elif kind == 'progress':
                    self.progress.configure(value=data)
                elif kind == 'status':
                    self.progress.configure(value=0)
                    self.status.set(data)
                elif kind == 'log':
                    self.append_log(data)
                elif kind == 'done':
                    self.set_busy(False)
                    self.progress.configure(value=100)
                    self.status.set(data)
                    self.append_log(data)
                    if self.close_after:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        if self.close_after and not self.busy:
            self.root.destroy()
            return
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            if messagebox.askyesno('Work in progress', 'Wait for this operation to finish, then close automatically?'):
                self.close_after = True
                self.status.set('Will close when the current operation finishes.')
        else:
            self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
