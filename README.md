# YTD3 desktop

A small Windows desktop app for saving YouTube audio as tagged MP3 files.
Requires Windows 10/11 (64-bit) and an internet connection. Download only content you have permission to save.

## Start on your computer

1. Install 64-bit Python 3.11 or newer from https://www.python.org/downloads/windows/ with the Python launcher enabled.
2. Extract this project into a folder you can write to.
3. Double-click `start_windows.bat`. First launch installs the dependencies (internet required).

FFmpeg is included through the `imageio-ffmpeg` dependency; no separate FFmpeg installation is needed. FFmpeg's executable is launched to convert audio to V0 variable-bitrate MP3. This does not increase the quality of the source audio.

## Use

1. Paste a YouTube video or playlist link and click **Preview link**.
2. For an actual album playlist, enable **Treat playlist as an album** before previewing. Leave it off for mixed playlists. A video URL containing `list=` loads the playlist; remove that parameter to load only the video.
3. Select each song and edit title, artist, album, album artist, track number, year, genre, and artwork URL. Edits are kept immediately in the current preview. Loading another preview replaces them. Blank optional fields are omitted from tags. Blank artwork URL means no cover.
4. **Open artwork preview** opens the current image URL in your browser. Use a direct JPEG or PNG URL for replacement art. YouTube thumbnails are suggestions, not verified album covers.
5. Choose a save folder, then click **Download all songs**. The app stays responsive and logs each result. Downloading is sequential; errors on one song do not stop the others. The folder is remembered for next launch.

The app preserves Live/Remix/featured-artist labels, but artist/title guesses still need human review. It does not query a music catalog for verified album or release information. Track and year fields are validated before downloading. Existing files are kept; duplicate names gain `(2)`, `(3)`, etc. Temporary files are removed on normal completion/failure. An abrupt termination may leave a `.ytd3-` folder, which can be deleted when the app is closed.

Artwork failure is logged and the tagged song is saved without a cover. Network operations run in the background; closing during an operation offers to wait for it to finish. There is no immediate cancellation or automatic retry. Protected, age-restricted, private, or unavailable videos may fail. This version has no login/cookie support. If YouTube changes, updating `pytubefix` within its supported major version may help.

The previous ReplayGain step was removed because it combined filtering with stream copying and suppressed failures. This version does not normalize volume or write ReplayGain tags.

## Share with friends

On a Windows computer, double-click `build_windows.bat`. It installs the build tools and creates `dist\YTD3\YTD3.exe` plus its supporting files, including FFmpeg. ZIP the **entire `dist\YTD3` folder**, then share the ZIP. Friends extract it and run `YTD3.exe`; they do not need Python. Do not send just the EXE.

Build and try the app on Windows before distributing it. Unsigned applications may trigger Windows reputation warnings. Do not disable security tools; code signing is an option for wider distribution. Bundled dependencies have their own licenses; retain the bundled license files when sharing. FFmpeg licensing information: https://www.ffmpeg.org/legal.html and https://github.com/imageio/imageio-ffmpeg.

## Development

- `YTdownloader.py`: Tkinter desktop UI, background workers, progress, settings.
- `ytd_core.py`: URL validation, metadata suggestions, stream selection, conversion, ID3 tags, safe output.
- `tests/test_core.py`: metadata, file safety, artwork failure, and a real conversion/tagging round trip using a generated tone (no YouTube download).

Run checks with `python -m unittest discover -s tests -v` after installing requirements. Importing the modules does not start a download or prompt for input.

### Build using GitHub instead

This project includes `.github/workflows/windows.yml`. After these files are uploaded to your repository, open **Actions → Build Windows desktop app → Run workflow**. A successful run produces a **YTD3-Windows** artifact at the bottom of the run page. Download and extract that ZIP, then open `YTD3.exe`. The workflow runs the automated checks on Windows, packages the app, and checks that the executable stays open at startup. A successful build still needs a manual test with a real video before sharing.

The downloadable source project is not a prebuilt Windows executable. Windows packaging and live YouTube behavior have not been verified in the Linux development environment.
