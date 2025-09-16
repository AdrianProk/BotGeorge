import requests
import os

def download_random_media(subreddit, download_folder="media"):
    # URL für die zufällige Anfrage
    url = f"https://www.reddit.com/r/{subreddit}/random.json"
    headers = {"User-Agent": "python:random.reddit.post:v1.0 (by /u/your_username)"}
    response = requests.get(url, headers=headers)
    
    # Überprüfen, ob die Anfrage erfolgreich war
    if response.status_code == 200:
        data = response.json()
        post = data[0]["data"]["children"][0]["data"]
        
        # Überprüfen, ob es sich um einen Bild-, GIF- oder Video-Link handelt
        media_url = post.get("url")
        if media_url and (media_url.endswith((".jpeg",".jpg", ".png", ".gif", ".mp4"))):
            media_type = media_url.split('.')[-1]  # Dateityp herausfinden (z.B. jpg, gif, mp4)
            
            # Dateiinhalt herunterladen
            media_data = requests.get(media_url).content
            
            # Verzeichnis erstellen, falls nicht vorhanden
            if not os.path.exists(download_folder):
                os.makedirs(download_folder)
            
            media_path = os.path.join(download_folder, f"leMeme.{media_type}")
            with open(media_path, "wb") as media_file:
                media_file.write(media_data)
                
            print(f"{media_type.upper()} erfolgreich heruntergeladen: {media_path}")
            return media_path
        
        elif post.get("is_video"):
            video_url = post["media"]["reddit_video"]["fallback_url"]
            
            # Video herunterladen
            video_data = requests.get(video_url).content
            
            if not os.path.exists(download_folder):
                os.makedirs(download_folder)
             
            video_path = os.path.join(download_folder, "leMeme.mp4")
            with open(video_path, "wb") as video_file:
                video_file.write(video_data)
            
            print(f"Video erfolgreich heruntergeladen: {video_path}")
            return video_path
        else:
            print("Der Post enthält kein unterstütztes Medienformat.")
            print(media_url)
            download_random_media(subreddit)
            return None
    else:
        print("Fehler bei der Anfrage:", response.status_code)
        return None

# Beispiel für die Nutzung
# subreddit = "Animemes"
# download_random_media(subreddit)
