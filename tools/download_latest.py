from src.config.settings import settings
from src.services.youtube_downloader import YouTubeDownloader

if __name__ == "__main__":
    print("Channel IDs:", settings.youtube_channel_ids)
    d = YouTubeDownloader()
    res = d.download_channel_videos(settings.youtube_channel_ids[0], max_videos=1)
    print("Downloaded:", res)
