"""Isolated operations with process-tree pause/cancel and atomic event files."""
from dataclasses import asdict
import contextlib
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import psutil


class EventWriter:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.counter = 0

    def __call__(self, kind, value):
        self.counter += 1
        destination = self.folder / f'{self.counter:08d}.json'
        staging = destination.with_suffix('.tmp')
        staging.write_text(json.dumps({'kind': kind, 'value': value}), encoding='utf-8')
        staging.replace(destination)


def _worker_main(kind, payload, folder):
    # Frozen windowed applications have no stdout/stderr. Keep third-party
    # output private to the task instead of opening a console or crashing.
    from ytd_core import Track, preview, download_track, format_error, DownloadFailure, read_saved_tags
    folder = Path(folder)
    emit = EventWriter(folder / 'events')
    with (folder / 'worker.log').open('w', encoding='utf-8') as log, \
         contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            if kind == 'preview':
                tracks = preview(payload['url'], payload['album_mode'],
                                 cookies_file=payload.get('cookies_file'), workdir=folder, report=emit)
                emit('result', [asdict(track) for track in tracks])
            elif kind == 'download':
                target, warning = download_track(Track(**payload['track']), payload['output'],
                    progress=lambda percent: emit('progress', percent), workdir=payload['media_dir'],
                    cookies_file=payload.get('cookies_file'), session_dir=folder, report=emit)
                emit('result', {'path': str(target), 'warning': warning, 'tags': read_saved_tags(target)})
            elif kind == 'diagnostic':
                from ytd_smoke import worker_diagnostic
                emit('result', worker_diagnostic(folder))
            else:
                raise ValueError('Unknown operation.')
        except Exception as exc:
            emit('error', {'message': format_error(exc),
                           'stop_batch': isinstance(exc, DownloadFailure) and exc.stop_batch,
                           'video_only': isinstance(exc, DownloadFailure) and exc.video_only,
                           'needs_sign_in': isinstance(exc, DownloadFailure) and exc.needs_sign_in})


class WorkerJob:
    def __init__(self, kind, payload):
        output = Path(payload['output']) if kind == 'download' else None
        if output:
            output.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='.ytd3-', dir=output)
        self.private = tempfile.TemporaryDirectory(prefix='ytd3-task-') if output else None
        self.folder = Path(self.private.name if self.private else self.temporary.name)
        if output:
            payload = dict(payload, media_dir=self.temporary.name)
        self.events = self.folder / 'events'
        self.events.mkdir()
        self.kind = kind
        self.paused = False
        self.cancelled = False
        self.suspended = []
        self.killed = []
        self.exit_polls = 0
        self.process = mp.get_context('spawn').Process(target=_worker_main,
            args=(kind, payload, str(self.folder)), daemon=True)
        try:
            self.process.start()
        except Exception:
            self.temporary.cleanup()
            if self.private:
                self.private.cleanup()
            raise

    @property
    def alive(self):
        return self.process.is_alive()

    def drain(self):
        messages = []
        for path in sorted(self.events.glob('*.json')):
            message = json.loads(path.read_text(encoding='utf-8'))
            path.unlink()
            messages.append((message['kind'], message['value']))
        return messages

    def pause(self):
        if self.paused or not self.alive:
            return
        root = psutil.Process(self.process.pid)
        suspended = []
        try:
            root.suspend()  # Stop the worker from creating more helpers.
            suspended.append(root)
            for child in root.children(recursive=True):
                try:
                    child.suspend()
                    suspended.append(child)
                except psutil.NoSuchProcess:
                    pass
        except (psutil.Error, OSError):
            for process in reversed(suspended):
                with contextlib.suppress(psutil.Error, OSError):
                    process.resume()
            raise
        self.suspended = suspended
        self.paused = True

    def resume(self):
        for process in reversed(self.suspended):
            with contextlib.suppress(psutil.NoSuchProcess):
                process.resume()
        self.suspended = []
        self.paused = False

    def cancel(self):
        self.cancelled = True
        if not self.alive:
            return
        try:
            root = psutil.Process(self.process.pid)
            with contextlib.suppress(psutil.Error):
                root.suspend()
            self.killed = root.children(recursive=True)
            for process in reversed(self.killed):
                with contextlib.suppress(psutil.NoSuchProcess):
                    process.kill()
            with contextlib.suppress(psutil.NoSuchProcess):
                root.kill()
        except psutil.NoSuchProcess:
            pass

    def close(self):
        self.process.join(timeout=0.3)
        if self.alive:
            self.cancel()
        self.process.join(timeout=1)
        if self.killed:
            psutil.wait_procs(self.killed, timeout=1)
        self.process.close()
        warnings = []
        for temporary in (self.private, self.temporary):
            if temporary:
                try:
                    temporary.cleanup()
                except OSError as exc:
                    warnings.append(f'Temporary folder could not be removed: {temporary.name}: {exc}')
        return '\n'.join(warnings)
