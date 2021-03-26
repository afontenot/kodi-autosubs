# autosubs.py for Kodi

A project to automatically create reasonable default settings in
Kodi for subtitles and audio tracks.

## How it works

Kodi has stupid default settings for playing subtitles. You can
always enable subtitles in your native language, or always enable
forced subtitles, but there's no way to automatically play subtitles
in your native language *only* when the audio is *not* in your native
language. This script fixes this problem by enabling subtitles 
manually for these files.

Currently I'm taking the following approach:

1. Scan files passed to the script for their audio / subtitle data.

2. For each file, determine whether the default audio is English (or
the language you select). If not:

3. Get the default subtitle. Prioritizing external subtitles (which
are assumed to be in the same location as the file, with '.srt' as
the extension), then internal forced subtitles, then internal 
subtitles with the "default" flag set, then any other subtile tagged
with your language in the file.

4. Offer the user a choice of which subtitle to make the default. The
user can just press enter to select the default subtitle found in 
step 3.

## Usage

    python3 autosubs.py kodi.videos.db file1.mkv file2.mkv

    python3 autosubs.py -a -u -f -q -l en MyVideos119.db movies/*.mkv

You need to have all of the files you want to update subtitles for
already in the Kodi database (usually named something like 
MyVideos119.db). It should be safe to use this script while Kodi is 
running, but if you're paranoid you can shut down Kodi first.

There are several options:

    --updateonly

This skips reading files that already have subtitles set in the Kodi
database. This is faster, because it means we don't have to 
scan the original files. It's also safer, because there's no risk 
you'll accidentally overwrite the settings for files you've already
configured. But there's some chance you'll miss files that were
incorrectly configured before.

    --fastmode

This checks to see whether the audio track selected by Kodi is already
in your native language, and if so, it skips the file. At present, 
files with the default audio tagged *in the file* with your selected 
language are skipped anyway (since presumably they don't need 
subtitles set), but this is safer than fast mode because there's some 
chance the data in Kodi will be inaccurate, or that a dub will be the 
selected audio track. That said, turning this on is *much* faster 
because most files won't need to be scanned, even if they don't have 
subtitle settings.

    --quiet

This is designed to allow you to automatically run it whenever new
files are added to Kodi's database. It implies both `--updateonly`
and `--fastmode`, and also applies the default option (when there
is one), or does nothing (when there isn't).

    --audio

This enables the feature described below. It's designed to detect
cases where you might want to use a secondary audio track as the
default, for example when the original mono mix is included as a
secondary track in the file.

    --language

Lets you set the language that the program will compare audio tracks
and subtitles to. You can use either the full name or a two or three
digit code (like "en" or "eng" for English). This is used as described
above to decide whether a file needs subtitles automatically enabled.

## Non-default audio track settings

This script also has the ability to let you set a non-default audio
track as the default. For example, maybe a file has both the original
mono mix and a low quality 5.1 upsample, and the latter is default.

Since many files have more than one audio track, the script uses some 
heuristics to figure out when it might make sense to do this. Right 
now, this is triggered when there is an audio track that is not the 
default (according to mediainfo) that is not tagged as a commentary 
track in the file's metadata. This probably has a bunch of false 
positives for tracks with dubs, but I don't have many files like this 
and couldn't think of an obvious way to avoid it. If you don't want 
to use the audio feature, simply don't add the `-a` flag.

## Requirements

 * Python 3.8+
 * pymediainfo
 * pycountry
