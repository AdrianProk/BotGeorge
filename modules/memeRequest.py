import requests
import os

# Reddit blocks anonymous JSON requests (403 / login redirect), so we use
# meme-api.com, a free proxy that returns random posts from a subreddit.
API_URL = "https://meme-api.com/gimme/{subreddit}/{count}"
HEADERS = {"User-Agent": "python:botgeorge.memes:v1.1"}
SUPPORTED = (".jpeg", ".jpg", ".png", ".gif", ".mp4")


def download_random_media(subreddit, download_folder="media"):
    try:
        response = requests.get(API_URL.format(subreddit=subreddit, count=10),
                                headers=HEADERS, timeout=15)
    except requests.RequestException as exc:
        print("Error in the request:", exc)
        return None

    if response.status_code != 200:
        print("Error in the request:", response.status_code)
        return None

    for post in response.json().get("memes", []):
        if post.get("nsfw"):
            continue
        media_url = post.get("url", "")
        if not media_url.lower().endswith(SUPPORTED):
            continue

        media_type = media_url.rsplit(".", 1)[-1].lower()
        try:
            media = requests.get(media_url, headers=HEADERS, timeout=30)
            media.raise_for_status()
        except requests.RequestException as exc:
            print("Media download failed:", exc)
            continue

        os.makedirs(download_folder, exist_ok=True)
        media_path = os.path.join(download_folder, f"leMeme.{media_type}")
        with open(media_path, "wb") as media_file:
            media_file.write(media.content)

        print(f"{media_type.upper()} successful download: {media_path}")
        return media_path

    print(f"No supported media found in r/{subreddit}.")
    return None
