# Original behavior and regression coverage

Baseline: [`YTdownloader.py` at 2744eb2](https://github.com/ArcannabisGarden/YTD3/blob/2744eb2cd410bc6908400f77cbe176d79ca3954f/YTdownloader.py).

The desktop app initially replaced too much of this workflow. This inventory records the original behavior, what version 0.3.3 restores, and the deliberate differences. Regression checks are in `tests/test_original_behavior.py`; general metadata, download, and UI checks remain in the other test files.

| Original capability | Current behavior |
| --- | --- |
| Single-video and playlist modes | Both supported. Normal saved-playlist URLs preview the playlist; watch/share URLs with `list=RD…` preview only the linked video instead of requesting its dynamic radio mix. A single video is never given a fabricated album based on its song title. |
| Playlists treated as albums | **Album** is the default again. Playlist title and position supply album name and track number. **Auto** and **Mixed playlist** remain explicit alternatives. Missing album titles fall back to Unknown Album. |
| Folder named after the cleaned album | Restored. Songs with an album tag go under `Save to / album name /`. Songs without an album tag stay directly under Save to. This also organizes individual songs when they have an album tag. |
| `clean_artist_name` removes ` - Topic` | Retained and applied to structured artist fields as well as uploader/channel guesses. |
| `split_artist_from_title` handles hyphen, en dash, em dash, spaced colon, and pipe | Restored. A known artist prefix is stripped first, including without spaces and regardless of capitalization. |
| `force_strip_artist_prefix` removes duplicated artist names | Applied to extractor `track` fields too. The reported `seether - Gasoline` example becomes artist Seether, title Gasoline. |
| `clean_track_title` removes leftover boundary punctuation and whitespace | Restored for isolated separators such as ` - Gasoline - `. Genuine punctuation such as Love-Hate, -Human, and Fine Again - Acoustic is retained. |
| Playlist title cleaned into an album name | Artist prefixes, isolated leading separators, and recognized Album/Full Album/Official/EP/LP wrapper labels are removed. Leading `album -` and `Album:` type labels are stripped, including when nested with an artist prefix. Actual album words and version labels are kept. |
| Windows filename sanitation | Restored `:` → `꞉`, plus replacements for forbidden Windows characters. Reserved device names, empty names, and excessive length also have safeguards. |
| WebM audio preference with other-audio fallback | Restored through yt-dlp's format selector. The best available WebM audio is preferred, then other audio, then a combined stream if necessary. |
| V0 VBR MP3 via libmp3lame | Retained, using FFmpeg directly. No additional encode is performed when repairing an existing app-created MP3. |
| ID3v2.3 title, artist, album artist, album, track number | Retained, plus editable year and genre. New files also contain encoder and V0 quality information again. |
| Thumbnail artwork embedded as front cover | Restored with maxresdefault → hqdefault → sddefault JPEG fallbacks for YouTube thumbnails. WebP, PNG, JPEG, GIF, and other supported raster images are decoded and embedded as JPEG for player compatibility. |
| Delete intermediate audio after successful conversion | Temporary files are cleaned on normal completion, failure, and cancellation. Complete MP3s are published atomically. |
| Download progress and logs | Replaced terminal colors/progress with desktop progress, per-song state, and exportable logs. |

## Explicit differences

- Version 0.3.3 saves title-only filenames (`Disclaimer II/Gasoline.mp3`), keeping the artist in its tag. Earlier artist-prefixed filenames are recognized and renamed during repair. The UI previews the output path, and the log reads actual saved ID3 values back after each successful operation.

- The original title normalization could remove words inside legitimate names, and removed every parenthesized/bracketed version label. The current cleanup removes recognized promotional labels while retaining Live/Remix/featured-artist information and genuine punctuation. The preview remains editable.
- The original album normalization removed the words album/EP/LP/official/playlist anywhere. The current version removes identified wrapper labels and prefixes, while retaining actual names such as The Album.
- Album artist can differ from song artist, particularly for collaborations/compilations. The field remains editable.
- The original ReplayGain invocation combined an audio filter with stream copying and suppressed the resulting FFmpeg errors. It did not provide working normalization. Normalization remains unimplemented; existing ReplayGain tags are preserved during metadata repair.
- The unreliable download implementation was replaced with yt-dlp. Cookie sessions, process-tree Pause/Resume/Cancel, bounded retries, age-gate skipping, and safe file publication are additions around the original music workflow.

## Repairing files created by earlier desktop versions

Re-preview the playlist in version 0.3.3, check the fields, choose the same Save to parent folder, and click **Download / update songs**. A valid existing MP3 is matched by its embedded source video URL, copied to temporary storage, updated, and published in the album folder. Existing audio bytes, lyrics, comments, ratings, and unrelated tags are retained. Optional year/genre and other optional metadata already present are retained when the preview has no value; explicit field changes, including clearing a value, take priority. The previous file is removed only after the updated copy is safely saved; if that removal fails, the log identifies that the old copy remains.

A successful cover update replaces the front-cover data with JPEG. If a replacement cannot be fetched, an existing cover is retained and a warning is logged. Repeating the operation with the same cover URL reuses an already-valid cached JPEG cover. Clearing the artwork field explicitly removes cover art.

Unrelated files are never overwritten. Audio with no trustworthy source tag (including MP3s made by the original script) is not silently claimed or moved. Those files cannot be matched safely by this repair path; a new download receives its own filename.
