# spotifydl

## Original Work

The main code is the work of [rbouteiller](https://github.com/rbouteiller) and has been extended with additional
functionality.

## Description

This Python script allows you to download Spotify playlists, top tracks, liked tracks, recommendations, and search
results as MP3 files. It leverages the Spotify API via **Tekore** and downloads audio from **YouTube** using **yt-dlp**,
while tagging MP3 files with metadata using **eyed3**.

## Features

1. Download songs from a chosen Spotify playlist.
2. Download recommended songs based on a Spotify playlist.
3. Download your top Spotify tracks.
4. Download recommendations based on your top tracks.
5. Download liked (saved) tracks from your Spotify profile.
6. Create new Spotify playlists from recommendations or top tracks.
7. Search for tracks, artists, albums, and playlists, with the option to download tracks from search results.
8. Choose a preferred audio quality (190kbps or 320kbps).
9. Intelligent YouTube search with fallback mechanisms:

    * Retry without the album title if the initial search fails.
    * Retry with ASCII-only characters for titles containing special characters.
10. Tags downloaded MP3 files with artist, title, album, album artist, genre, track number, and album art.

## Dependencies

* **tekore** – Access the Spotify API.
* **yt-dlp** – Download and convert audio from YouTube.
* **eyed3** – Edit ID3 tags in MP3 files.
* **urllib** – Fetch album artwork.

Install via pip:

```bash
pip install tekore yt-dlp eyed3
```

## Setup and Usage

1. **Spotify Developer App:**
   Create a new app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/) with a redirect URI:
   `http://127.0.0.1:5000/`.

2. **API Credentials:**
   Save your `client_id` and `client_secret` in `CLIENT_ID.txt` and `CLIENT_SECRET.txt` respectively.

3. **FFmpeg:**
   Set `ffmpeg_path` in the script to the location of `ffmpeg.exe` on your system.

4. **Run Script**

```bash
python spotify.py
```

1. **Follow On-Screen Prompts**
   On the first run, your browser will open to authenticate your Spotify account. The script then presents a menu-driven
   interface. Select your desired action and follow prompts.

## Security Warning

Keep your `client_id` and `client_secret` private. Do not share them publicly, as they authenticate your access to
Spotify.

## Limitations

1. Songs are downloaded from YouTube, so tracks may differ slightly from Spotify originals.
2. Some tracks may not be available or downloadable due to YouTube restrictions.
3. Unicode and special characters in track names may occasionally affect matching; the script attempts fallback
   strategies to mitigate this.

## Disclaimer

Downloading copyrighted material without permission may be illegal in your country. This script is intended for
*educational and personal use only*. Respect copyright laws and the terms of service of Spotify and YouTube.

## Contribution

Contributions are welcome. Open issues or submit pull requests to improve functionality or fix bugs.

## License

This project is licensed under the MIT License. See the LICENSE file for details.