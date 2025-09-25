import yt_dlp
import os

def toMp3(url):
    try:
        ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [
                {
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '0'
                },
                { 
                    "key": "FFmpegThumbnailsConvertor",
                    "format": "jpg",
                },
                {
                    "key": "EmbedThumbnail",
                },
                {  
                    "key": "FFmpegMetadata",
                },
            ],
            "writethumbnail": True,
            "addmetadata": True,
            "postprocessor_args": {
                "EmbedThumbnail": ["-id3v2_version", "3"]
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            filenamepre = ydl.prepare_filename(info_dict)
            filename = os.path.splitext(filenamepre)[0] + '.mp3'
            
        return filename

    except:
        error = -1
        print(error)
        return error

