import requests
import os

def download_random_media(subreddit, download_folder="media"):
    url = f"https://old.reddit.com/r/{subreddit}/random.json"
    headers = {"User-Agent": "python:random.reddit.post:v1.0 (by /u/your_username)"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        post = data[0]["data"]["children"][0]["data"]
        
        media_url = post.get("url")
        if media_url and (media_url.endswith((".jpeg",".jpg", ".png", ".gif", ".mp4"))):
            media_type = media_url.split('.')[-1] 
            
            media_data = requests.get(media_url).content
            
            if not os.path.exists(download_folder):
                os.makedirs(download_folder)
            
            media_path = os.path.join(download_folder, f"leMeme.{media_type}")
            with open(media_path, "wb") as media_file:
                media_file.write(media_data)
                
            print(f"{media_type.upper()} successful download: {media_path}")
            return media_path
        
        elif post.get("is_video"):
            video_url = post["media"]["reddit_video"]["fallback_url"]
            
            # Video download
            video_data = requests.get(video_url).content
            
            if not os.path.exists(download_folder):
                os.makedirs(download_folder)
             
            video_path = os.path.join(download_folder, "leMeme.mp4")
            with open(video_path, "wb") as video_file:
                video_file.write(video_data)
            
            print(f"Video downloaded successfully: {video_path}")
            return video_path
        else:
            print("The post does not contain a supported media format.")
            print(media_url)
            download_random_media(subreddit)
            return None
    else:
        print("Error in the request:", response.status_code)
        return None


