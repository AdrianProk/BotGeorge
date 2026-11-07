import os
import yt_dlp
from yt_dlp.utils import match_filter_func

MAX_DURATION_S = 15 * 60


def toMp3(url):
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'match_filter': match_filter_func(f'duration <= {MAX_DURATION_S}'),
            'max_filesize': 200 * 1024 * 1024,
            'socket_timeout': 30,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web_safari']
                }
            },
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '0'
                },
                {
                    'key': 'FFmpegThumbnailsConvertor',
                    'format': 'jpg',
                },
                {
                    'key': 'EmbedThumbnail',
                },
                {
                    'key': 'FFmpegMetadata',
                },
            ],
            'writethumbnail': True,
            'addmetadata': True,
            'postprocessor_args': {
                'EmbedThumbnail': ['-id3v2_version', '3']
            },
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            if not info_dict:
                return None

            filenamepre = ydl.prepare_filename(info_dict)
            filename = os.path.splitext(filenamepre)[0] + '.mp3'

        if os.path.exists(filename):
            return filename

        return None

    except Exception as exc:
        print(f"MP3 conversion failed: {exc}")
        return None

