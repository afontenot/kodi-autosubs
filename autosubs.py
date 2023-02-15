import argparse
import json
import websocket
import sqlite3
import sys
from os.path import exists
from types import SimpleNamespace

from pymediainfo import MediaInfo
from pycountry import languages


# convert a user supplied language code to a pycountry language
def argparse_langcode(s: str):
    return languages.get(alpha_2=s) or languages.get(alpha_3=s) or languages.get(name=s)


# Handles everything to do with media files and mediainfo
class FileManager:
    def __init__(self, fpath, defaultlang_aa):
        # get data: mediainfo, track lists, and add any external subtitles,
        # then get defaults
        self.fpath = fpath
        info = MediaInfo.parse(fpath)
        self.audiotracks = list(filter(lambda x: x.track_type == "Audio", info.tracks))
        self.subtracks = list(filter(lambda x: x.track_type == "Text", info.tracks))

        # put all the properties we can access with this class in the namespace
        self.default_audiotrack = self.get_default_audiotrack()
        self.extra_audiotracks = self.get_extra_audiotracks()
        self.preferred_subtrack = self.get_preferred_subtrack(defaultlang_aa)
        self.external_subtrack = self.has_external_subtrack()

    # return audio track in order of pref: default, first listed
    def get_default_audiotrack(self):
        marked_default = list(filter(lambda x: x.default == "Yes", self.audiotracks))
        if marked_default:
            if len(marked_default) > 1:
                print("Warning: more than 1 default audio track")
            return marked_default[0]
        return self.audiotracks[0]

    # get any audio tracks that aren't default or commentary using heuristics
    def get_extra_audiotracks(self):
        extra_atracks = []
        for atrack in self.audiotracks:
            if atrack == self.default_audiotrack:
                continue
            if atrack.title and "commentary" in atrack.title.lower():
                continue
            extra_atracks.append(atrack)
        return extra_atracks

    # return preferred language lang_aa track: forced, default, first listed
    def get_preferred_subtrack(self, lang_aa):
        localtracks = list(filter(lambda x: x.language == lang_aa, self.subtracks))
        if not localtracks:
            return None
        # attempt removing SDH tracks
        if len(localtracks) > 1:
            clean = list(filter(lambda x: "SDH" not in (x.title or ""), localtracks))
            if clean:
                localtracks = clean
        marked_forced = list(filter(lambda x: x.forced == "Yes", localtracks))
        if marked_forced:
            if len(marked_forced) > 1:
                print("Warning: more than 1 forced sub track")
            return marked_forced[0]
        marked_default = list(filter(lambda x: x.default == "Yes", localtracks))
        if marked_default:
            if len(marked_default) > 1:
                print("Warning: more than 1 default sub track")
            return marked_default[0]
        return localtracks[0]

    # rather simplistic heuristic to check for an external subtitle (.srt)
    # finds either filename.mkv.srt or filename.srt, good enough for my needs
    def has_external_subtrack(self):
        longpath = self.fpath + ".srt"
        shortpath = self.fpath[:-3] + "srt"
        if exists(longpath) or exists(shortpath):
            return True


# handles access to the SQLite database and modifying file information there
class KodiManager:
    def __init__(self, dbpath):
        self.conn = sqlite3.connect(dbpath)
        self.cur = self.conn.cursor()

    # allows checking whether a path exists in the Kodi database
    # note: matches only the file name, not the whole path. FIXME?
    def getfid(self, filmpath):
        fname = filmpath.split("/")[-1]
        self.cur.execute(f'select idFile from movie where c22 like "%{fname}"')
        res = self.cur.fetchone()
        if res is None:
            return None
        return res[0]

    def get_default_audio_lang(self, fid):
        self.cur.execute(f"select AudioStream from settings where idFile={fid}")
        audiostream = self.cur.fetchone()
        if audiostream and audiostream[0] != -1:
            audiostream = audiostream[0]
        else:
            audiostream = 0
        self.cur.execute(
            f"select strAudioLanguage from streamdetails where idFile={fid} and iStreamType=1"
        )
        astreams = self.cur.fetchall()
        # note: this will probably be an intermittent problem until a release
        # with https://github.com/xbmc/xbmc/pull/20247 is made
        # their fix doesn't clean up old code for fetching stream details,
        # but interested users should probably backport the changes anyway
        if len(astreams) == 0:
            print(
                "Warning: file does not contain audio tracks or streamdetails missing. Did Kodi run mediainfo?"
            )
            return None
        if audiostream + 1 > len(astreams):
            print(
                "Warning: selected audio stream does not refer to any stream inside the file. Assuming external."
            )
            return None
        return astreams[audiostream][0]

    def has_subtitle_settings(self, fid):
        self.cur.execute(
            f"select SubtitleStream,SubtitlesOn from settings where idFile={fid}"
        )
        res = self.cur.fetchone()
        return res and res[0] != -1 and res[1] == 1

    def has_audio_settings(self, fid):
        self.cur.execute(f"select AudioStream from settings where idFile={fid}")
        res = self.cur.fetchone()
        return res and res[0] != -1

    # just creates a new row in settings with the given id and default settings
    def insert_settings_row(self, rowid):
        default_settings = {
            "Deinterlace": 1,
            "ViewMode": 0,
            "ZoomAmount": 1.0,
            "PixelRatio": 1.0,
            "VerticalShift": 0.0,
            "AudioStream": -1,
            "SubtitleStream": -1,
            "SubtitleDelay": 0.0,
            "SubtitlesOn": 1,
            "Brightness": 50.0,
            "Contrast": 50.0,
            "Gamma": 20.0,
            "VolumeAmplification": 0.0,
            "AudioDelay": 0.0,
            "ResumeTime": 0,
            "Sharpness": 0.0,
            "NoiseReduction": 0.0,
            "NonLinStretch": 0,
            "PostProcess": 0,
            "ScalingMethod": 1,
            "DeinterlaceMode": "NULL",
            "StereoMode": 0,
            "StereoInvert": 0,
            "VideoStream": -1,
            "TonemapMethod": 1,
            "TonemapParam": 1.0,
            "Orientation": 0,
            "CenterMixLevel": 0,
        }
        self.cur.execute(f"insert into settings (idFile) values ({rowid})")
        for name, val in default_settings.items():
            self.cur.execute(f"update settings set {name}={val} where idFile={rowid}")
        self.conn.commit()

    def set_subtrack(self, fid, tracknum, force=False):
        self.cur.execute(f"select SubtitleStream from settings where idFile={fid}")
        res = self.cur.fetchone()
        # if the SubtitleStream is already set, flip the subs on if the chosen
        # sub is what the user selected, else bail out unless forced
        if res and res[0] != -1:
            if res[0] == tracknum:
                self.cur.execute(
                    f"update settings set SubtitlesOn=1 where idFile={fid}"
                )
                self.conn.commit()
                return True
            elif not force:
                return False
        if not res:
            self.insert_settings_row(fid)
        self.cur.execute(
            f"update settings set SubtitleStream={tracknum}, SubtitlesOn=1 where idFile={fid}"
        )
        self.conn.commit()
        return True

    def set_atrack(self, fid, tracknum, force=False):
        # if a default stream is already set, bail unless forced
        self.cur.execute(f"select AudioStream from settings where idFile={fid}")
        res = self.cur.fetchone()
        if res and res[0] != -1:
            if res[0] == tracknum:
                return True
            elif not force:
                return False
        if not res:
            self.insert_settings_row(fid)
        self.cur.execute(
            f"update settings set AudioStream={tracknum} where idFile={fid}"
        )
        self.conn.commit()
        return True


# The base class for the program. See run() for default execution.
class AutosubsProgram:
    def __init__(self):
        self.db = None
        self.buffereddata = ""

    def parseargs(self):
        parser = argparse.ArgumentParser(
            description="Set subtitle and audio track setings in Kodi automatically."
        )
        parser.add_argument(
            "-d",
            "--database",
            help="location of the Kodi database (e.g. MyVideos116.db)",
            required=True,
        )
        parser.add_argument(
            "-l",
            "--language",
            help="""Set your native language. Only files that Kodi will play
                in a different language than the one you choose will have their
                subtitles activated or deactivated by this script. The language
                will also be used to find the correct subtitles automatically.
                You can use the full language name or a two-letter or
                three-letter ISO code. Default: English (en)""",
            default="English",
            type=argparse_langcode,
        )
        subp = parser.add_subparsers(
            title="Mode",
            help="""Set the program mode to use.""",
            required=True,
            dest="command",
        )

        # live mode: use 'quiet' settings to adjust newly added files
        watch_parser = subp.add_parser(
            "watch",
            help="""Automatically run the script (in safe / quiet mode)
                whenever Kodi updates its video library. Local TCP access
                must be enabled.""",
        )
        watch_parser.add_argument(
            "ws",
            metavar="ws://host:port",
            default="ws://localhost:9090",
            nargs="?",
            help="Websocket address to connect to Kodi. Default: ws:localhost:9090",
        )

        # normal mode: scan specified files
        scan_parser = subp.add_parser(
            "scan",
            help="""Scan and update settings for specified files""",
            epilog="""Leaving the three speed-up modes disabled is
                recommended on your first run of the script. You can enable them
                (or just use --quiet) after that, then leave them off for
                specific files.""",
        )
        scan_parser.add_argument(
            "-u",
            "--updateonly",
            help="""Skip updating files that already have subtitles set, or
                updating audio tracks on files that have audio tracks set.""",
            action="store_true",
        )
        scan_parser.add_argument(
            "-f",
            "--fastmode",
            help="""Skip files that have your chosen language as the default
                audio track in the Kodi database. Otherwise, the script will
                attempt to verify the language with mediainfo, set forced subs,
                and so on.""",
            action="store_true",
        )
        scan_parser.add_argument(
            "-q",
            "--quiet",
            help="""Does the default option without prompting. Implies
                --updateonly and --fastmode for maximum safety. Incompatible
                with --audio. Intended for automated use, for interactive try
                --updateonly --fastmode.""",
            action="store_true",
        )
        scan_parser.add_argument(
            "-a",
            "--audio",
            help="""Enable the audio stream adjustment mode. Detects when
                there might be an alternative audio stream that should be the
                default, so that you can easily switch to it. Attempts to use
                heuristics to avoid commentary tracks. Intended to make it
                easier to find and play original mono audio tracks, which are
                sometimes included as secondary tracks in the file.""",
            action="store_true",
        )
        scan_parser.add_argument(
            "files",
            help="""list of media files to scan (e.g. *.mkv); note that the
                files need to be in Kodi's database already for this to work""",
            nargs="+",
        )

        self.args = parser.parse_args()

        if self.args.command == "watch":
            self.args.quiet = True

        if self.args.quiet:
            self.args.updateonly = True
            self.args.fastmode = True
            self.args.audio = False

    # lets the user pick subtitles to use from a handy selection with defaults,
    # or picks the default automatically if the quiet flag is set
    def choose_subtrack(self, film):
        for strack in film.subtracks:
            # print the default sub track with brackets for emphasis
            if strack == film.preferred_subtrack and film.default_audiotrack.language:
                print(
                    f"{strack.stream_identifier}: [{strack.language} | {strack.title} | {strack.codec_id} | forced: {strack.forced}]"
                )
            else:
                print(
                    f"{strack.stream_identifier}:  {strack.language} | {strack.title} | {strack.codec_id} | forced: {strack.forced}"
                )
        inp = ""
        if not self.args.quiet:  # don't prompt if quiet mode
            if film.default_audiotrack.language:
                inp = input(
                    "\nEnter track number to use, 'n' to cancel, enter to accept: "
                )
            else:
                inp = input("\nEnter track number to use, enter to cancel: ")
        if film.default_audiotrack.language and inp == "":
            return int(film.preferred_subtrack.stream_identifier)
        elif inp.isdecimal():
            inp = int(inp)
            if inp >= 0 and inp < len(film.subtracks):
                return inp
        return None

    # let the user pick the audio track to use
    def choose_atrack(self, film):
        for atrack in film.audiotracks:
            print(f"{atrack.stream_identifier}:  {atrack.language} | {atrack.title}")
        inp = input("\nEnter track number to use, enter to cancel: ")
        if inp.isdecimal():
            inp = int(inp)
            if inp >= 0 and inp < len(film.audiotracks):
                return inp
        return None

    # the central method for finding subtitles and updating Kodi's settings
    def update_subtitles(self, film, fid):
        # If we can detect an external srt with simple heuristics, then
        # create a simple placeholder for it in the subtitles list.
        if film.external_subtrack:
            # We set stream_identifier to 1 + the maximum index of the subs list
            # because Kodi uses this number internally for external subs.
            srt = {
                "title": "EXTERNAL",
                "forced": "No",
                "language": self.args.language.alpha_2,
                "default": "No",
                "stream_identifier": len(film.audiotracks),
                "codec_id": "srt",
            }
            ext_subtrack = SimpleNamespace(**srt)
            film.subtracks.append(ext_subtrack)
            # If the film has an external sub track, almost certainly that's
            # the one that the user prefers, so make it the default choice.
            film.preferred_subtrack = ext_subtrack

        # if the film has subs and the audio language is either not default
        # or unknown, ask the user what to do (or take automatic choice)
        if film.subtracks and (
            not film.default_audiotrack
            or film.default_audiotrack.language != self.args.language.alpha_2
        ):
            if film.preferred_subtrack:
                print("\nSetting sub track on", film.fpath, "\n")
                subtrack_choice = self.choose_subtrack(film)
                if subtrack_choice is not None:
                    result = self.db.set_subtrack(fid, subtrack_choice)
                    # don't overwrite when using quiet mode, for safety
                    if not result and not self.args.quiet:
                        print("Different subtitle previously set.")
                        choice = input("Overwrite (y/n)? ")
                        if choice != "y":
                            print("Skipping.\n")
                        else:
                            self.db.set_subtrack(fid, subtrack_choice, True)
                else:
                    print("Skipping.\n")
            else:
                print("No subtitles were detected in your language!")
        elif film.preferred_subtrack and film.preferred_subtrack.forced == "Yes":
            print("Note: film has a forced track.")

    # the central method for finding audio tracks and updating Kodi's settings
    def update_audio(self, film, fid):
        # check if file mediainfo indicates non-identifiable audio tracks
        if film.extra_audiotracks:
            print(
                "\nSome additional tracks could not be positively identified as commentaries:\n"
            )
            atrack_choice = self.choose_atrack(film)
            if atrack_choice is not None:
                result = self.db.set_atrack(fid, atrack_choice)
                if not result:
                    print("Different audio stream previously set.")
                    choice = input("Overwrite (y/n)? ")
                    if choice != "y":
                        print("Skipping.\n")
                    else:
                        self.db.set_atrack(fid, atrack_choice, True)

    def _run(self, files):
        self.db = KodiManager(self.args.database)

        for filecount, fpath in enumerate(files):
            print(f"[{filecount+1}/{len(files)}]", fpath)

            # make sure Kodi already knows about the file
            fid = self.db.getfid(fpath)
            if not fid:
                print(f"{fpath} was not in the database!")
                continue

            # check whether flags allow updating subtitles for this file
            can_update_subtitles = True
            if (
                self.args.fastmode
                and self.db.get_default_audio_lang(fid) == self.args.language.alpha_3
            ):
                can_update_subtitles = False
            if self.args.updateonly and self.db.has_subtitle_settings(fid):
                can_update_subtitles = False

            # then perform the update
            film = None
            if can_update_subtitles:
                film = FileManager(fpath, self.args.language.alpha_2)
                self.update_subtitles(film, fid)

            # check whether flags allow updating audio track for this file
            can_update_audio = self.args.audio
            if self.args.updateonly and self.db.has_audio_settings:
                can_update_audio = False

            # then perform the update
            if can_update_audio:
                if not film:
                    film = FileManager(fpath, self.args.language.alpha_2)
                self.update_audio(film, fid)

        # close database connection
        self.db.conn.close()
        self.db = None

    # receive json messages from websocket
    # note: this blocks, but that's appropriate for this app since we want
    # to wait indefinitely for messages from Kodi. Also, Kodi doesn't support
    # websocket pings (it actually refuses to reply, which violates spec) so
    # implementing any sort of keepalive feature would be counterproductive.
    def _listen_json(self, sock):
        try:
            data = sock.recv()
            return json.loads(data)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON:", data)
        except KeyboardInterrupt:
            sock.close()
            if self.db:
                self.db.conn.close()
            sys.exit()

    def live(self):
        sock = websocket.WebSocket()
        sock.connect(self.args.ws)
        movies = set()
        while True:
            data = self._listen_json(sock)
            print("<", data)
            if data.get("method") == "VideoLibrary.OnUpdate":
                if data["params"]["data"].get("added"):
                    if data["params"]["data"]["item"]["type"] == "movie":
                        movieid = data["params"]["data"]["item"]["id"]
                        movies.add(movieid)
            elif data.get("method") == "VideoLibrary.OnScanFinished":
                moviepaths = []
                for movieid in movies:
                    cmd = {
                        "jsonrpc": "2.0",
                        "method": "VideoLibrary.GetMovieDetails",
                        "params": {
                            "movieid": movieid,
                            "properties": ["file"],
                        },
                        "id": "autosubs-getmoviedetails",
                    }
                    cmd = json.dumps(cmd)
                    print(">", cmd)
                    sock.send(cmd)
                    while True:
                        data = self._listen_json(sock)
                        print("<", data)
                        if not data.get("id") == "autosubs-getmoviedetails":
                            continue
                        if "result" in data:
                            path = data["result"]["moviedetails"]["file"]
                            moviepaths.append(path)
                        break
                if moviepaths:
                    self._run(moviepaths)
                movies.clear()

    # main function when run as a program
    def run(self):
        self.parseargs()
        if self.args.command == "watch":
            self.live()
        else:
            self._run(self.args.files)


if __name__ == "__main__":
    asp = AutosubsProgram()
    asp.run()
