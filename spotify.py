# Download spotify playlist to mp3
from difflib import SequenceMatcher

import tekore as tk
import os
import yt_dlp
import eyed3
import urllib
import re

# Spotify API
client_id_path = "CLIENT_ID.txt"  # 'YOUR_CLIENT_ID_LOCATION_HERE'
client_secret_path = "CLIENT_SECRET.txt"  # 'YOUR_CLIENT_SECRET_LOCATION_HERE'
user_token_path = "USER_TOKEN.txt"  # Will be filled automatically, don't worry about filling this
ffmpeg_path = "D:\\Programs\\ffmpeg.exe"  # 'YOUR_FFMPEG_LOCATION_HERE'
download_path = "E:\\Music\\NewDL"  # 'YOUR_DOWNLOAD_FOLDER_LOCATION_HERE'

# If you use Windows, make sure to use \\ instead of \.
# It should look something like this 'C:\\ffmpeg\\bin\\ffmpeg.exe'

redirect_uri = 'http://localhost:5000/'

# Read client_id
if os.path.exists(client_id_path):
    with open(client_id_path, 'r') as f:
        client_id = f.read().strip()
else:
    raise FileNotFoundError("Missing file: {client_id_path}")

# Read client_secret
if os.path.exists(client_secret_path):
    with open(client_secret_path, 'r') as f:
        client_secret = f.read().strip()
else:
    raise FileNotFoundError(f"Missing file: {client_secret_path}")

# Read user_token (if it exists)
user_token = None
if os.path.exists(user_token_path):
    with open(user_token_path, 'r') as f:
        user_token = f.read().strip()

user_token = user_token.strip() if user_token else None
if user_token is None:
    print(f"{user_token_path} not found. Will be created automatically later.")

# Test a token if it is valid
try:
    spotify = tk.Spotify(user_token)
    spotify.current_user()
except tk.HTTPError:
    # If a token is invalid, get a new token
    user_token = tk.prompt_for_user_token(
        client_id,
        client_secret,
        redirect_uri,
        scope=tk.scope.every
    )
    # Save user_token in a file
    with open('USER_TOKEN.txt', 'w') as f:
        f.write(str(user_token))
    spotify = tk.Spotify(user_token)


class MyLogger:
    def debug(self, msg):
        # For compatibility with yt-dlp, both debug and info are passed into debug
        # You can distinguish them by the prefix '[debug]'
        if msg.startswith('[debug] '):
            pass
        else:
            self.info(msg)

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        print(msg)


def my_hook(d):
    if d['status'] == 'finished':
        print('Done downloading, now converting ...')


ydl_opts = {
    'ffmpeg_location': ffmpeg_path,
    'format': 'bestaudio/best',
    'extractaudio': True,
    'outtmpl': '%(title)s.%(ext)s',
    'addmetadata': True,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '320',
    }],
    'logger': MyLogger(),
    'progress_hooks': [my_hook],
}


def get_yt_track_url(track):
    """Get the most accurate YouTube URL for a Spotify track."""
    song = track.name
    artist = track.artists[0].name if track.artists else ""
    album = track.album.name if track.album else ""
    target_title = f"{song} {artist}".lower()
    target_duration_ms = getattr(track, 'duration_ms', 0)

    query = f"{song} {artist} {album}" # official audio"
    query = re.sub(r'[^\w\s]', '', query)  # remove punctuation

    print(f"Searching YouTube for: {query}")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            results = ydl.extract_info(f"ytsearch10:{query}", download=False)['entries']
            if not results:
                print(f"No YouTube results for {song} by {artist}")
                return None

            # Compute similarity between YouTube title and Spotify track
            def similarity(a, b):
                return SequenceMatcher(None, a.lower(), b.lower()).ratio()

            # Filter out videos with wildly different duration (optional)
            def duration_diff(entry):
                video_ms = (entry.get('duration') or 0) * 1000
                return abs(video_ms - target_duration_ms)

            # Sort by title similarity first, then duration
            best_match = min(
                results,
                key=lambda e: (duration_diff(e), -SequenceMatcher(None, e['title'].lower(), target_title).ratio())
            )

            print(f"Selected YouTube video: {best_match['title']}")
            return best_match['webpage_url']

        except Exception as e:
            print(f"Error searching YouTube for {song} by {artist}: {e}")
            return None


def sanitize_filename(name: str) -> str:
    """
    Remove or replace characters that are not allowed in filenames.
    """
    # Replace invalid characters with underscore
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Strip trailing/leading spaces and dots (Windows doesn’t like them)
    sanitized = sanitized.strip().rstrip('.')
    return sanitized


def songs_downloader(base_folder, tracks):
    """
    Save as: <base or none>/<Artist>/<Album>/<NN - Song>.mp3
    Prevents duplicates when base == album (e.g., 'Album/Artist/Album/Song').
    """
    successful = 0
    failed = 0
    failedList = []
    for i, track in enumerate(tracks):
        print(f"Tracks processed: {i}/{len(tracks)}")

        # Raw fields from Spotify (with safe fallbacks)
        raw_song = getattr(track, "name", None) or "Unknown Title"
        raw_artist = (track.artists[0].name if getattr(track, "artists", None) else "Unknown Artist")
        raw_album = (track.album.name if getattr(track, "album", None) else "Unknown Album")

        # Sanitize for filesystem
        song = sanitize_filename(raw_song)
        artist = sanitize_filename(raw_artist)
        album = sanitize_filename(raw_album)

        # Filename (with track number if present)
        track_num = getattr(track, "track_number", None)
        file_name = f"{track_num:02d} - {song}.mp3" if isinstance(track_num, int) and track_num > 0 else f"{song}.mp3"

        # Base folder handling (avoid Album/Artist/Album nesting)
        base = sanitize_filename(base_folder) if base_folder else ""
        if base and base.lower() == album.lower():
            base = ""  # prevent duplicate album segment

        # Build final destination: <base>/<Artist>/<Album>/
        parts = [p for p in [base, artist, album] if p]
        destination_path = os.path.join(download_path, *parts) if parts else os.path.join(artist, album)
        full_destination = os.path.join(destination_path, file_name)

        # Skip if already there
        if os.path.exists(full_destination):
            print(f"Already downloaded: {full_destination}")
            continue

        # Ensure folder exists
        os.makedirs(destination_path, exist_ok=True)

        # yt-dlp options per-track so we don't mutate globals
        ydl_local = dict(ydl_opts)
        ydl_local['outtmpl'] = os.path.join(destination_path, os.path.splitext(file_name)[0] + ".%(ext)s")

        print(f"Downloading: {raw_song} by {raw_artist}")
        try:
            with yt_dlp.YoutubeDL(ydl_local) as ydl:
                youtube_url = get_yt_track_url(track)
                if not youtube_url:
                    print(f"Could not find YouTube URL for {raw_song} by {raw_artist}. Skipping.")
                    failed += 1
                    failedList.append(f"{raw_song} by {raw_artist}")
                    continue

                with yt_dlp.YoutubeDL(ydl_local) as ydl:
                    ydl.download([youtube_url])

            # If the postprocessor altered the name, normalize to our intended filename
            if not os.path.exists(full_destination):
                mp3s = [file_name for file_name in os.listdir(destination_path) if file_name.lower().endswith('.mp3')]
                if mp3s:
                    newest = max((os.path.join(destination_path, file_name) for file_name in mp3s),
                                 key=os.path.getmtime)
                    if newest != full_destination:
                        try:
                            os.rename(newest, full_destination)
                        except Exception as e:
                            print(f"Warning: couldn't rename {newest} -> {full_destination}: {e}")

            # Tagging
            if os.path.exists(full_destination):
                audiofile = eyed3.load(full_destination)
                if audiofile is None:
                    print(f"Warning: couldn't load mp3 for tagging: {full_destination}")
                    continue
                if audiofile.tag is None:
                    audiofile.initTag()

                audiofile.tag.artist = raw_artist
                audiofile.tag.title = raw_song
                audiofile.tag.album = raw_album
                if getattr(track, "album", None) and getattr(track.album, "artists", None):
                    audiofile.tag.album_artist = track.album.artists[0].name

                # Genre from Spotify artist
                try:
                    artist_id = track.artists[0].id
                    genres = spotify.artist(artist_id).genres
                    if genres:
                        audiofile.tag.genre = genres[-1]
                except Exception as e:
                    print(f"Warning: couldn't get genre: {e}")

                if isinstance(track_num, int) and track_num > 0:
                    audiofile.tag.track_num = track_num

                # Album art
                try:
                    if getattr(track, "album", None):
                        images = getattr(track.album, "images", [])
                        if images:
                            imagedata = urllib.request.urlopen(images[0].url).read()
                            audiofile.tag.images.set(3, imagedata, 'image/jpeg')
                except Exception as e:
                    print(f"Warning: couldn't embed cover art: {e}")

                audiofile.tag.save()
                print(f"Saved: {full_destination}")
                successful += 1
            else:
                print(f"Failed to find the downloaded file at: {full_destination}")
                failed += 1
                failedList.append(f"{raw_song} by {raw_artist}")

        except yt_dlp.utils.DownloadError as e:
            print(f"Error downloading '{raw_song}' by '{raw_artist}': {e}. Skipping.")
            failed += 1
            failedList.append(f"{raw_song} by {raw_artist}")
            continue
        except Exception as e:
            print(f"Unexpected error for '{raw_song}' by '{raw_artist}': {e}. Skipping.")
            failed += 1
            failedList.append(f"{raw_song} by {raw_artist}")
            continue

    for failedTrack in failedList:
        print(f"Failed to download: {failedTrack}")


print("Logged in as " + spotify.current_user().email)


def choose_quality():
    while True:
        quality = input("Choose the quality of songs (190 or 320) [default: 320]: ")
        if quality in ['', '190', '320']:
            ydl_opts['postprocessors'][0]['preferredquality'] = quality if quality else '320'
            break
        print("Invalid input, please enter 190, 320, or press Enter for default")


def list_playlists():
    playlists = spotify.playlists(spotify.current_user().id)
    for i, playlist in enumerate(playlists.items):
        print(i, end=". ")
        print(playlist.name)
    return playlists


def get_playlist_tracks(playlist):
    tracks = []
    playlist_uri = playlist.uri.split(":")[-1]
    results = spotify.playlist_items(playlist_uri)
    tracks.extend(results.items)
    while results.next:
        results = spotify.next(results)
        tracks.extend(results.items)
    return tracks


def list_liked_songs():
    liked_songs = []
    results = spotify.saved_tracks()
    liked_songs.extend(results.items)
    while results.next:
        results = spotify.next(results)
        liked_songs.extend(results.items)
    return liked_songs


def get_recommendations(tracks):
    track_ids = [t.track.id for t in tracks]
    recommendations = spotify.recommendations(track_ids=track_ids).tracks
    return recommendations


def get_top_tracks(limit=5):
    top_tracks = spotify.current_user_top_tracks(limit=limit).items
    return top_tracks


def create_playlist(name, description):
    user = spotify.current_user()
    playlist = spotify.playlist_create(
        user.id,
        name,
        public=False,
        description=description
    )
    return playlist


def add_tracks_to_playlist(playlist, tracks):
    uris = [t.uri for t in tracks]
    spotify.playlist_add(playlist.id, uris=uris)


def menu():
    print("1. Download songs from playlist")
    print("2. Download songs from recommendations")
    print("3. Download songs from top tracks")
    print("4. Download songs from top tracks recommendations")
    print("5. Create playlist from recommendations")
    print("6. Create playlist from top tracks")
    print("7. Create playlist from top tracks recommendations")
    print("8. Search")
    print("9. Exit")
    print("Extra options:")
    print("10. Choose quality of songs")
    print("11. Download liked songs")  # New option for downloading liked songs
    try:
        action = int(input("Enter option: "))
    except ValueError:
        print("Invalid input")
        return menu()
    return action


def playlist_tracks_to_tracks(playlist_tracks):
    tracks = []
    for playlist_track in playlist_tracks:
        tracks.append(playlist_track.track)
    return tracks


def search(query, types=('track', 'artist', 'album')):
    results = spotify.search(query, types=types, limit=10)
    return results


def search_tracks(query):
    results = search(query, types=('track',))
    return results


def search_artists(query):
    results = search(query, types=('artist',))
    return results


def search_albums(query):
    results = search(query, types=('album',))
    return results


def search_playlists(query):
    results = search(query, types=('playlist',))
    return results


def search_menu():
    print("1. Search tracks")
    print("2. Search artists")
    print("3. Search albums")
    print("4. Exit")
    try:
        action = int(input("Enter option: "))
        if action == 1:
            query = input("Enter query: ")
            results = search_tracks(query)
            for i, track in enumerate(results[0].items):
                print(i, end=". ")
                print(track.name, end=" - ")
                print(track.artists[0].name)
            return query, results[0].items
        elif action == 2:
            query = input("Enter query: ")
            results = search_artists(query)
            for i, artist in enumerate(results[0].items):
                print(i, end=". ")
                print(artist.name)
            return query, results[0].items
        elif action == 3:
            query = input("Enter query: ")
            results = search_albums(query)
            for i, album in enumerate(results[0].items):
                print(i, end=". ")
                print(album.name, end=" - ")
                print(album.artists[0].name)
            return query, results[0].items
        elif action == 4:
            return None
    except ValueError:
        print("Invalid input, try again.")
        search_menu()
    return None


def post_search_menu(query, results):
    print()
    print("1. Download songs from search results")
    print("2. Create playlist from search results")
    print("3. Exit")
    try:
        action = int(input("Enter option: "))
    except ValueError:
        print("Invalid input")
        return post_search_menu(query, results)
    if action == 1:
        # Choose a song to download (one or more)
        songs_index = input("Enter songs number, all for all: ")
        if songs_index == 'all':
            songs_downloader("Search : " + query, results)
        else:
            # Split could be " ", "." or "-"
            songs_index = songs_index.replace(',', ' ').replace('.', ' ').replace('-', ' ').split()
            songs_index = [int(i) for i in songs_index]
            songs_downloader("Search : " + query, [results[i] for i in songs_index])
    elif action == 2:
        playlist = create_playlist(query, "Created by spotify-downloader")
        add_tracks_to_playlist(playlist, results)
        print("Playlist created: " + playlist.name)
    elif action == 3:
        return None
    else:
        print("Invalid input")
        return post_search_menu(query, results)
    return None


def main():
    while True:
        action = menu()
        if action == 1:
            playlists = list_playlists()
            try:
                playlist_index = int(input("Enter playlist number: "))
                playlist = playlists.items[playlist_index]
            except (ValueError, IndexError):
                print("Invalid playlist number. Try again.")
                continue  # loops back in main()
            tracks = get_playlist_tracks(playlist)
            tracks = playlist_tracks_to_tracks(tracks)
            songs_downloader("Music", tracks)
        elif action == 2:
            playlists = list_playlists()
            try:
                playlist_index = int(input("Enter playlist number: "))
                playlist = playlists.items[playlist_index]
            except (ValueError, IndexError):
                print("Invalid playlist number. Try again.")
                continue  # loops back in main()
            tracks = get_playlist_tracks(playlist)
            recommendations = get_recommendations(tracks)
            songs_downloader("Music", recommendations)
        elif action == 3:
            top_tracks = get_top_tracks(int(input("Enter number of top tracks: ")))
            songs_downloader("Music", top_tracks)
        elif action == 4:
            top_tracks = get_top_tracks(int(input("Enter number of top tracks: ")))
            recommendations = get_recommendations(top_tracks)
            songs_downloader("Music", recommendations)
        elif action == 5:
            playlists = list_playlists()
            playlist = playlists.items[int(input("Enter playlist number: "))]
            tracks = get_playlist_tracks(playlist)
            recommendations = get_recommendations(tracks)
            playlist = create_playlist(playlist.name + " recommendations", "Recommended songs from " + playlist.name)
            add_tracks_to_playlist(playlist, recommendations)
        elif action == 6:
            top_tracks = get_top_tracks()
            playlist = create_playlist("Top tracks", "Top tracks from user")
            add_tracks_to_playlist(playlist, top_tracks)
        elif action == 7:
            top_tracks = get_top_tracks()
            recommendations = get_recommendations(top_tracks)
            playlist = create_playlist("Top tracks recommendations", "Recommended songs from top tracks")
            add_tracks_to_playlist(playlist, recommendations)
        elif action == 8:
            execute_search, results = search_menu()
            post_search_menu(execute_search, results)
        elif action == 9:
            exit()
        elif action == 10:
            choose_quality()
        elif action == 11:  # New action for downloading liked songs
            liked_songs = list_liked_songs()
            liked_tracks = [item.track for item in liked_songs]
            songs_downloader("Music", liked_tracks)


if __name__ == "__main__":
    main()
