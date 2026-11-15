import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import psutil

from ytd_jobs import EventWriter, WorkerJob


def tree_worker(kind, payload, folder):
    """Real parent/child processes with a heartbeat, no external network."""
    emit = EventWriter(Path(folder) / 'events')
    heartbeat = Path(folder) / 'heartbeat.txt'
    script = "import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\ni=0\nwhile True:\n p.write_text(str(i)); i+=1; time.sleep(0.05)\n"
    child = subprocess.Popen([sys.executable, '-c', script, str(heartbeat)],
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    emit('ready', {'pid': child.pid, 'heartbeat': str(heartbeat)})
    try:
        while True:
            time.sleep(0.1)
    finally:
        child.kill()
        child.wait()


def wait_until(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError('Timed out waiting for process state.')


def active(pid):
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


class JobTests(unittest.TestCase):
    def test_real_pause_resume_cancel_cleans_worker_tree_and_partial_files(self):
        with tempfile.TemporaryDirectory() as output:
            completed = Path(output) / 'completed.mp3'
            completed.write_bytes(b'keep completed songs')
            with patch('ytd_jobs._worker_main', tree_worker):
                job = WorkerJob('download', {'output': output})
            folder = job.folder
            messages = []
            child_pid = None
            try:
                def ready():
                    messages.extend(job.drain())
                    return bool(messages)
                wait_until(ready)
                data = messages[0][1]
                child_pid = data['pid']
                heartbeat = Path(data['heartbeat'])
                wait_until(heartbeat.exists)
                job.pause()
                self.assertTrue(job.paused)
                before = heartbeat.read_text()
                time.sleep(0.2)
                self.assertEqual(heartbeat.read_text(), before, 'child must stop while paused')
                job.resume()
                self.assertFalse(job.paused)
                wait_until(lambda: heartbeat.read_text() != before)
                # Cancel must work even if Pause was pressed again.
                job.pause()
                job.cancel()
                wait_until(lambda: not job.alive)
                wait_until(lambda: not active(child_pid))
            finally:
                job.close()
            self.assertFalse(folder.exists())
            self.assertEqual(completed.read_bytes(), b'keep completed songs')

    def test_worker_returns_useful_error_instead_of_exiting_silently(self):
        job = WorkerJob('unknown', {})
        messages = []
        try:
            def ready():
                messages.extend(job.drain())
                return any(kind == 'error' for kind, _ in messages)
            wait_until(ready)
            error = next(value for kind, value in messages if kind == 'error')
            self.assertIn('Unknown operation', error['message'])
        finally:
            job.close()

    def test_atomic_events_ignore_incomplete_files(self):
        with tempfile.TemporaryDirectory() as folder:
            emit = EventWriter(folder)
            emit('status', 'Ready')
            staging = Path(folder) / '00000002.tmp'
            staging.write_text('{incomplete')
            events = sorted(Path(folder).glob('*.json'))
            self.assertEqual(len(events), 1)
            self.assertEqual(json.loads(events[0].read_text())['value'], 'Ready')
