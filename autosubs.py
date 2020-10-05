import argparse
import sqlite3
from os.path import exists
from types import SimpleNamespace

from pymediainfo import MediaInfo

# constants
default_settings = {'Deinterlace': 1, 'ViewMode': 0, 'ZoomAmount': 1.0,
                    'PixelRatio': 1.0, 'VerticalShift': 0.0, 'AudioStream': -1,
                    'SubtitleStream': -1, 'SubtitleDelay': 0.0, 'SubtitlesOn': 1,
                    'Brightness': 50.0, 'Contrast': 50.0, 'Gamma': 20.0,
                    'VolumeAmplification': 0.0, 'AudioDelay': 0.0,
                    'ResumeTime': 0, 'Sharpness': 0.0, 'NoiseReduction': 0.0,
                    'NonLinStretch': 0, 'PostProcess': 0, 'ScalingMethod': 1,
                    'DeinterlaceMode': 'NULL', 'StereoMode': 0, 'StereoInvert': 0,
                    'VideoStream': -1, 'TonemapMethod': 1, 'TonemapParam': 1.0,
                    'Orientation': 0, 'CenterMixLevel': 0}


# kind of naive, but works for my external subs
# find filename.mkv.srt or filename.srt and return with tracknum given
def get_external_subtrack(fpath, tracknum):
    srt = {'title': "EXTERNAL", 'forced': "No", 'language': "en", 
           'default': "No", 'stream_identifier': tracknum, 'codec_id': "srt"}
    longpath = fpath + '.srt'
    shortpath = fpath[:-3] + 'srt'
    if exists(longpath) or exists(shortpath):
        return SimpleNamespace(**srt)

# return audio track in order of pref: default, first listed
def get_default_audio_track(audiotracks):
    marked_default = list(filter(lambda x: x.default == "Yes", audiotracks))
    if marked_default:
        if len(marked_default) > 1:
            print("Warning: more than 1 default audio track")
        return marked_default[0]
    return audiotracks[0]

# return English track in order of pref: forced, default, first listed
def get_default_sub_track(subtracks):
    subtracks = list(filter(lambda x: x.language == "en", subtracks))
    if not subtracks:
        return None
    # attempt removing SDH tracks
    if len(subtracks) > 1:
        clean = list(filter(lambda x: not "SDH" in (x.title or ""), subtracks))
        if clean:
            subtracks = clean
    marked_forced = list(filter(lambda x: x.forced == "Yes", subtracks))
    if marked_forced:
        if len(marked_forced) > 1:
            print("Warning: more than 1 forced sub track")
        return marked_forced[0]
    marked_default = list(filter(lambda x: x.default == "Yes", subtracks))
    if marked_default:
        if len(marked_default) > 1:
            print("Warning: more than 1 default sub track")
        return marked_default[0]
    return subtracks[0]

def getfid(path):
    fname = path.split('/')[-1]
    cur.execute(f"select idFile from movie where c22 like \"%{fname}\"")
    fid = None
    try:
        return cur.fetchone()[0]
    except:
        print("Requested film not found in database.")
        return None

# just creates a new row in settings with the given id and default settings
def insert_settings_row(rowid):
    cur.execute(f"insert into settings (idFile) values ({rowid})")
    for name, val in default_settings.items():
        cur.execute(f"update settings set {name}={val} where idFile={rowid}")

def set_subtrack(fpath, tracknum):
    fid = getfid(fpath)
    if not fid:
        return
    # if a default stream is already set, ask for confirmation
    cur.execute(f"select SubtitleStream from settings where idFile={fid}")
    res = cur.fetchone()
    if res and res[0] != -1:
        if res[0] == tracknum:
            cur.execute(f"update settings set SubtitlesOn=1 where idFile={fid}")
            return
        print("Note: existing SubtitleStream set to:", res[0])
        choice = ""
        if not args.automatic:
            choice = input("Press y to continue, enter to cancel: ")
        if choice != "y":
            print("aborting\n")
            return
    if not res:
        insert_settings_row(fid)
    cur.execute(f"update settings set SubtitleStream={tracknum}, SubtitlesOn=1 where idFile={fid}")
    print("db update complete\n")

def set_atrack(fpath, tracknum):
    fid = getfid(fpath)
    if not fid:
        return
    # if a default stream is already set, ask for confirmation
    cur.execute(f"select AudioStream from settings where idFile={fid}")
    res = cur.fetchone()
    if res and res[0] != -1:
        if res[0] == tracknum:
            return
        print("Note: existing AudioStream set to:", res[0])
        choice = ""
        if not args.automatic:
            choice = input("Press y to continue, enter to cancel: ")
        if choice != "y":
            print("aborting\n")
            return
    if not res:
        insert_settings_row(fid)
    cur.execute(f"update settings set AudioStream={tracknum} where idFile={fid}")
    print("db update complete\n")


parser = argparse.ArgumentParser(
        description="Set subtitle and audio track setings in Kodi automatically.",
        epilog="""Leaving the three speed-up modes disabled is recommended 
        on your first run of the script. You can enable them (or just use 
        --automatic) after that, then leave them off for specific files.""")
parser.add_argument(
        '-u', '--updateonly', 
        help="""Skip updating files that already have subtitles set, or 
        updating audio tracks on files that have audio tracks set.""", 
        action='store_true')
parser.add_argument(
        '-f', '--fastmode', 
        help="""Skip files that have English as the first audio track in 
        the Kodi database. Otherwise, the script will attempt to verify 
        the language with mediainfo, set forced subs, and so on.""", 
        action='store_true')
parser.add_argument(
        '-a', '--automatic', 
        help="""Does the default option without prompting. Implies 
        --updateonly and --fastmode for maximum safety. Designed for 
        automated use, for interactive try --updateonly --fastmode.""", 
        action='store_true')
parser.add_argument(
        'database', 
        help="location of the Kodi database (e.g. MyVideos116.db)")
parser.add_argument(
        'files', 
        help="""list of media files to scan (e.g. *.mkv); note that the
        files need to be in Kodi's database already for this to work""", 
        nargs='+')

args = parser.parse_args()
if args.automatic:
    args.updateonly = True
    args.fastmode = True

conn = sqlite3.connect(args.database)
cur = conn.cursor()

for filecount, fpath in enumerate(args.files):
    print(f"[{filecount+1}/{len(args.files)}]", fpath)
    fid = getfid(fpath)
    if not fid: 
        continue

    # fast mode: exit if track is English
    if args.fastmode:
        cur.execute(f"select iStreamType,strAudioLanguage from streamdetails where idFile={fid}")
        engtrack = False
        for res in cur.fetchall():
            if res[0] == 1:
                if res[1] == "eng":
                    engtrack = True
                break
        if engtrack:
            continue
    
    # update mode: exit if subtitle settings already exist
    if args.updateonly:
        cur.execute(f"select SubtitleStream,SubtitlesOn from settings where idFile = \"{fid}\"")
        res = cur.fetchone()
        if res and res[0] != -1 and res[1] == 1:
            continue
                    
    # get data: mediainfo, track lists, and add any external subtitles, 
    # then get defaults
    info = MediaInfo.parse(fpath)
    audiotracks = list(filter(lambda x: x.track_type == "Audio", info.tracks))
    subtracks = list(filter(lambda x: x.track_type == "Text", info.tracks))
    # request external subs with len(subtracks) 
    # so that the sub will have the highest track number
    # this appears to match Kodi's numbering, but it's kind of a hack
    ext_subtrack = get_external_subtrack(fpath, len(subtracks))
    if ext_subtrack:
        subtracks.append(ext_subtrack)

    default_atrack = get_default_audio_track(audiotracks)
    default_strack = get_default_sub_track(subtracks)

    # first look at subtitles
    # for films with un-tagged audio and some sub options
    #  -> offer the user to set subtitle of choice, no defaults
    # for films with a non-english default audio and some subtitle options
    #  -> offer the user to set the detected default subtitle, or choose one
    if subtracks and (not default_atrack.language or default_atrack.language != "en"):
        if default_strack:
            print("\nSetting sub track on", fpath, "\n")
            for strack in subtracks:
                if strack == default_strack and default_atrack.language:
                    print(f"{strack.stream_identifier}: [{strack.language} | {strack.title} | {strack.codec_id} | forced: {strack.forced}]")
                else:
                    print(f"{strack.stream_identifier}:  {strack.language} | {strack.title} | {strack.codec_id} | forced: {strack.forced}")
            inp = ""
            if not args.automatic: # don't prompt if --automatic
                if default_atrack.language:
                    inp = input("\nEnter track number to use, 'n' to cancel, enter to accept: ")
                else:
                    inp = input("\nEnter track number to use, enter to cancel: ")
            if default_atrack.language and inp == "":
                set_subtrack(fpath, int(default_strack.stream_identifier))
            elif inp.isdecimal():
                inp = int(inp)
                if inp >= 0 and inp < len(subtracks):
                    set_subtrack(fpath, inp)
            else:
                print("track refused, continuing...\n")
        else:
            print("Warning: no subtitles found for this file.")
    elif default_strack and default_strack.forced == "Yes":
        print("Note: film has a forced track")
   
    # now we look at audio streams
    # update mode: exit if audiostream settings already exist
    if args.updateonly:
        cur.execute(f"select AudioStream from settings where idFile={fid}")
        res = cur.fetchone()
        if res and res[0] != -1:
            continue

    # make a list of any tracks that aren't default or commentary
    extra_atracks = []
    for atrack in audiotracks:
        if atrack == default_atrack:
            continue
        if atrack.title and "commentary" in atrack.title.lower():
            continue
        extra_atracks.append(atrack)

    # ask user whether they want to make one of these tracks the default
    if extra_atracks:
        print("\nSome additional tracks could not be positively identified as commentaries:\n")
        for extra_atrack in extra_atracks:
            print(f"{extra_atrack.stream_identifier}:  {extra_atrack.language} | {extra_atrack.title}")
        inp = ""
        if not args.automatic:
            inp = input("\nEnter track number to use, enter to cancel: ")
        if inp.isdecimal():
            inp = int(inp)
            if inp >= 0 and inp < len(audiotracks):
                set_atrack(fpath, inp)
        else:
            print("Audio tracks rejected.\n")
    conn.commit()

conn.close()
