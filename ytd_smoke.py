"""Offline packaged-app check: worker, Node, HTTP audio, FFmpeg, and tags."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import math
from pathlib import Path
import struct
import subprocess
import threading
import time
import wave


def make_tone(path):
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
        audio.writeframes(b''.join(struct.pack('<h', int(10000 * math.sin(2 * math.pi * 440 * i / 44100)))
                                   for i in range(22050)))


class SilentHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def worker_diagnostic(folder):
    from mutagen.mp3 import MP3
    from PIL import Image
    from yt_dlp.utils import Popen
    from ytd_core import node_path, fetch_audio, convert, write_tags, Track
    folder = Path(folder)
    for name in ('lib.min.js', 'core.min.js'):
        if not files('yt_dlp_ejs.yt.solver').joinpath(name).is_file():
            raise RuntimeError(f'Missing bundled JavaScript component: {name}')
    output, _, code = Popen.run([node_path(), '--version'], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=15)
    if code or not output.startswith('v'):
        raise RuntimeError('The bundled Node runtime did not start.')
    inputs = folder / 'input'
    inputs.mkdir()
    make_tone(inputs / 'tone.wav')
    Image.new('RGBA', (64, 64), (120, 40, 20, 160)).save(inputs / 'cover.webp', 'WEBP')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SilentHandler, directory=str(inputs)))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        source = fetch_audio(f'http://127.0.0.1:{server.server_port}/tone.wav', folder)
        converted = folder / 'test.mp3'
        convert(source, converted)
        warning = write_tags(converted, Track('https://youtu.be/example', 'example', 'Test Song', 'Test Artist',
                            album='Test Album', track='1', artwork=f'http://127.0.0.1:{server.server_port}/cover.webp'))
        if warning:
            raise RuntimeError(warning)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
    audio = MP3(converted)
    if audio.info.length < 0.4 or str(audio.tags['TALB']) != 'Test Album' or str(audio.tags['TRCK']) != '1':
        raise RuntimeError('Audio or metadata round trip failed.')
    cover = audio.tags.getall('APIC')
    if not cover or cover[0].mime != 'image/jpeg' or not cover[0].data.startswith(b'\xff\xd8\xff'):
        raise RuntimeError('WebP artwork was not embedded as a JPEG cover.')
    return {'worker': True, 'node': output.strip(), 'javascript_components': True,
            'local_http_download': True, 'conversion': True, 'metadata': True, 'webp_cover_as_jpeg': True}


def run_self_test(report_path):
    from ytd_jobs import WorkerJob
    result = {'success': False}
    job = None
    try:
        job = WorkerJob('diagnostic', {})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            for kind, value in job.drain():
                if kind == 'result':
                    result = {'success': True, 'checks': value}
                    return 0
                if kind == 'error':
                    raise RuntimeError(value['message'])
            time.sleep(0.1)
        raise TimeoutError('Packaged worker self-test timed out.')
    except Exception as exc:
        result = {'success': False, 'error': str(exc)}
        return 1
    finally:
        if job:
            job.close()
        Path(report_path).write_text(json.dumps(result, indent=2), encoding='utf-8')
