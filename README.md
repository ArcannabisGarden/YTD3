# YTD3 desktop 0.3.2

A Windows desktop app for saving YouTube audio as tagged MP3 files. Requires Windows 10/11 (64-bit) and an internet connection. Download content you have permission to save.

## Run on Windows

Download the **YTD3-Windows-0.3.2** artifact from the latest successful GitHub Actions run. Extract the whole ZIP into a new folder, then run **YTD3.exe**. Keep its supporting files together. The window title shows **0.3.2**. Python, FFmpeg, and Node do not need to be installed separately.

To run from source, install 64-bit Python 3.11 or newer from https://www.python.org/downloads/windows/ with its launcher enabled, extract the source, and double-click `start_windows.bat`. That development launcher opens one setup terminal to install dependencies; the packaged app runs without a console.

## Preview and song details

1. Paste a video or playlist link and click **Preview link**.
2. **Playlist type** defaults to **Album**, restoring the original script's playlist behavior: use the cleaned playlist name as album and playlist order as track numbers. Choose **Auto** to apply this only to YouTube album playlists (`OLAK…`), or **Mixed playlist** to keep supplied song metadata without inventing a playlist album.
3. Album and track number are visible in the song table. Select a song to edit title, artist, album, album artist, track number, year, genre, and artwork URL. Structured music metadata takes priority over title guesses. Your edits take priority when writing the final tags.
4. **Open artwork preview** opens the image URL in your browser. Use a direct image URL for replacement art. WebP, PNG, JPEG, GIF, and other supported raster images are converted to JPEG for embedding; blank means no cover. YouTube thumbnails are suggestions, not verified album covers.
5. Choose the Save to parent folder and click **Download / update songs**. Songs with album tags are saved inside a subfolder named after that album. Songs without an album stay directly in the parent folder.

A link containing `list=` loads that playlist. Remove the `list` parameter to preview only the linked video. Edits stay in the current preview; loading a different link replaces it. Only the output folder is remembered across app restarts.

## Pause, cancel, and retry

- **Pause / Resume** suspends the current worker and its helpers during preview, download, artwork retrieval, and conversion. Pause is also respected between songs. A long pause may cause the server connection to expire; use Retry unfinished songs if it cannot resume.
- **Cancel** stops the current worker/helper processes and removes that task's temporary files. Completed MP3 files are kept. The current incomplete song is discarded.
- **Retry unfinished songs** retries only songs not yet saved during the current preview. It does not redownload completed songs. After a restart, valid files already created by this app can be matched by source URL. They can have their tags and artwork updated and be organized into album folders without downloading or re-encoding the audio. Unknown optional metadata is kept from the existing file unless the corresponding field was explicitly edited. Unrelated files remain protected.
- Closing during work offers to cancel and clean up before exiting.
- **Save log** exports the original error reason, not just a generic retry count. Signed media URLs are removed from diagnostic messages. Do not include session files when reporting a problem.

The app downloads one song at a time with bounded network retries. A shared bot-verification, stream, or network failure stops the batch immediately; two consecutive other failures also stop it. Age-verification failures apply only to that video: the row shows Needs sign-in, the song stays unfinished, and other songs continue. Consecutive age-restricted videos do not stop the playlist. Remaining songs stay available to retry. An individual unavailable song may be skipped while the next is attempted. Each row shows Ready, Downloading, Saved, Needs sign-in, Failed, or Cancelled.

Unrelated files are never overwritten. Existing app-created songs can be updated atomically from a temporary copy. Filename collisions with other songs receive `(2)`, `(3)`, etc. Temporary audio stays in the output folder for atomic publication; session copies and internal task messages are kept separately in OS temporary storage. An abrupt system termination can leave `.ytd3-` folders, which can be deleted after the app is closed.

## YouTube connection errors

Version 0.3 replaces the prior pytubefix/SABR path with yt-dlp. The reported `SABR Maximum reload attempts reached. Stream protection status: PoToken PENDING` error means the earlier engine never obtained a usable playback token; increasing its reload count was not a solution.

The new engine has bounded retries, retains underlying HTTP/authentication errors, and uses bundled JavaScript support. Its helpers hide their Windows console windows; FFmpeg also runs without a console window.

YouTube may still require authentication or reject a request. If it explicitly asks you to sign in, **Load cookies.txt** can use a Netscape-format YouTube session file from your own browser. This is optional. Select it locally in the app; do not upload or send the file to anyone. The app uses a private temporary copy, leaves the original unchanged, removes its copy after the operation, and does not remember the selection after you close the app. **Clear** returns to unauthenticated requests. A session file does not guarantee that YouTube will allow a download, and it does not grant access to unavailable content.

For a message such as **Sign in to confirm your age**, first open that exact video in your own browser while signed in and check that your account is allowed to play it. The app cannot complete YouTube age verification for you. To use that account session in the app, follow the [official yt-dlp cookie export guide](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp), select the resulting local file with **Load cookies.txt**, then choose **Retry unfinished songs**. Do not send the session file in chat. Without a session file, version 0.3.1 skips the restricted video and continues other songs.

For repeated failures, use **Save log** and report the error text. No proxy rotation, repeated unbounded retries, or automatic use of browser accounts is performed.

## Audio and tags

WebM audio is preferred, with other-audio fallback, as in the original script. It is converted to V0 variable-bitrate MP3 with libmp3lame. Converting does not improve source quality. Mutagen writes ID3v2.3 tags; blank optional fields are omitted. Artwork is decoded from image bytes, converted to JPEG, and embedded as a front cover. YouTube thumbnail requests retain the original three JPEG fallbacks. Artwork failure is logged while the song is retained; an existing cover is kept if replacement fails. This version does not normalize volume or write ReplayGain tags.

## Build and share

On Windows, run `build_windows.bat`. It builds `dist\YTD3\YTD3.exe` and the required supporting files. ZIP and share the **entire `dist\YTD3` folder**, not just the EXE. Preserve bundled dependency license files. The application is unsigned; code signing can be added for wider distribution.

GitHub Actions builds the same folder and publishes **YTD3-Windows-0.3.2** as an artifact. Artifacts require GitHub sign-in and expire according to repository retention settings. Keep your own copy if needed longer. The workflow checks source tests, real worker pause/resume/cancel, and a packaged worker self-test that retrieves a generated audio tone over local HTTP, executes bundled Node/FFmpeg, and verifies MP3 tags plus a real WebP-to-JPEG embedded cover. These checks do not prove YouTube access from a user's connection. Live playback on the reported YouTube Music album could not be verified from the development cloud network because its gateway rejects that destination.

## Development

- `YTdownloader.py`: Tkinter UI, playlist mode, operation controls, unfinished-song state, log export.
- `ytd_core.py`: yt-dlp extraction, structured metadata and guesses, conversion, ID3 tags, safe output.
- `ytd_jobs.py`: spawned workers, process-tree control, temporary-file cleanup, atomic event messages.
- `ytd_smoke.py`: local audio fixture and the packaged-app self-test.
- `tests/`: original-script behavior regressions, metadata/defaults, artwork conversion and repair, local HTTP audio integration, file protection, real parent/child pause/resume/cancel, and UI workflows.

Install `requirements.txt`, then run `python -m unittest discover -s tests -v`. UI tests need a display and run on Windows CI. `YTD3.exe --self-test report.json` runs the offline packaged worker check without opening the GUI. Importing modules does not start a download or prompt for input.

See [Original behavior and regression coverage](ORIGINAL_BEHAVIOR.md) for the feature inventory and explicit differences from the original script. To repair earlier desktop downloads, re-preview them and use the same Save to parent folder. Files with matching source tags are repaired and organized without re-encoding; unrelated tags and audio are preserved.
