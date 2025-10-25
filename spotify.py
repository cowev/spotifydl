# Download spotify playlist to mp3
from difflib import SequenceMatcher

import tekore as tk
import os

import unicodedata
import yt_dlp
import eyed3
import urllib
import re
import concurrent.futures
import threading
from queue import Queue

# Spotify API
client_id_path = "CLIENT_ID.txt"  # 'YOUR_CLIENT_ID_LOCATION_HERE'
client_secret_path = "CLIENT_SECRET.txt"  # 'YOUR_CLIENT_SECRET_LOCATION_HERE'
user_token_path = "USER_TOKEN.txt"  # Will be filled automatically, don't worry about filling this
ffmpeg_path = "D:\\Programs\\ffmpeg.exe"  # 'YOUR_FFMPEG_LOCATION_HERE'
download_path = "E:\\NewDL"  # 'YOUR_DOWNLOAD_FOLDER_LOCATION_HERE'
max_workers = 5  # Number of parallel downloads (adjust based on your system)
download_queue = Queue()
lock = threading.Lock()

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
    # 'progress_hooks': [my_hook],
}


def make_ascii(query):
    """Convert to ASCII-friendly string, removing accents and unusual characters."""
    # Normalize Unicode characters
    nfkd_form = unicodedata.normalize('NFKD', query)
    # Encode to ASCII ignoring errors, then decode back to string
    ascii_query = nfkd_form.encode('ASCII', 'ignore').decode('ASCII')
    # Remove any leftover non-word characters (optional)
    ascii_query = re.sub(r'[^\w\s]', '', ascii_query)
    return ascii_query


def score_result(result, expected_song, expected_artist, target_duration=None):
    # Score a YouTube result based on title, artist, duration, and unwanted content.
    title = result['title'].lower()
    uploader = result.get('uploader', '').lower()
    duration = result.get('duration', 0)  # seconds
    score = 0

    # Fuzzy title match
    title_ratio = SequenceMatcher(None, expected_song.lower(), title).ratio()
    score += 0.3 * title_ratio

    # Artist in title
    if expected_artist.lower() in title:
        score += 0.2

    # Artist in uploader
    if expected_artist.lower() in uploader:
        score += 0.2

    # Duration match
    if target_duration:
        diff = abs(duration - target_duration)
        score += 0.5 * max(0, 1 - diff / 30)  # scale by +/-30s

    # Penalize unwanted content
    unwanted_terms = ['cover', 'karaoke', 'instrumental', 'remix', 'slowed', 'nightcore', 'reverb']
    for term in unwanted_terms:
        if term in title and term not in expected_song.lower():
            score -= 0.4

    return max(0, score)


def normalize_album(track):
    """
    Normalize the album name by removing unwanted tags or duplicates of the song name.
    """
    album = track.album.name if track.album else ""
    song = track.name

    # Remove the album if it is identical to the song name
    if album.lower().replace(" ", "") == song.lower().replace(" ", ""):
        album = ""
    # Remove unwanted album tags
    elif "scmp3" in album.lower():
        album = ""

    return album


def get_best_youtube_matches(track, max_results=10):
    song = track.name
    artist = track.artists[0].name if track.artists else ""
    album = normalize_album(track)
    target_duration = getattr(track, 'duration_ms', 0) / 1000

    def is_age_restricted_error(error):
        error_str = str(error).lower()
        age_indicators = [
            'age-restricted',
            'confirm your age',
            'sign in to confirm',
            'restricted content',
            'login required',
            'this video may be inappropriate',
            'content warning',
            'age verification required',
            'youtube account',
            'protected content'
        ]
        return any(indicator in error_str for indicator in age_indicators)

    def search_and_score(query):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                results = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)['entries']
                if not results:
                    return []
                scored_results = []
                for r in results:
                    scored_results.append({
                        'url': r['webpage_url'],
                        'score': score_result(r, song, artist, target_duration),
                        'title': r['title']
                    })
                return scored_results
        except yt_dlp.utils.DownloadError as e:
            if is_age_restricted_error(e):
                print(f"Age restriction detected during search. Trying alternative approach...")
                # Try a different search approach
                return search_with_alternative_method(query, max_results)
            else:
                print(f"Error searching YouTube: {e}")
                return []
        except Exception as e:
            print(f"Error searching YouTube: {e}")
            return []

    def search_with_alternative_method(query, max_results):
        """Alternative search method when age restrictions block regular search"""
        try:
            # Try a simpler search without extraction to get URLs
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl:
                results = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)['entries']
                if not results:
                    return []

                scored_results = []
                for r in results:
                    # For flat extraction, we have limited info, so use basic scoring
                    title = r.get('title', '').lower()
                    score = 0

                    # Basic title matching
                    title_ratio = SequenceMatcher(None, song.lower(), title).ratio()
                    score += 0.5 * title_ratio

                    # Artist in title
                    if artist.lower() in title:
                        score += 0.3

                    # Penalize unwanted content
                    unwanted_terms = ['cover', 'karaoke', 'instrumental', 'remix', 'slowed', 'nightcore', 'reverb']
                    for term in unwanted_terms:
                        if term in title and term not in song.lower():
                            score -= 0.4

                    scored_results.append({
                        'url': r['url'],
                        'score': max(0, score),
                        'title': r.get('title', 'Unknown')
                    })

                return sorted(scored_results, key=lambda x: x['score'], reverse=True)

        except Exception as e:
            print(f"Alternative search also failed: {e}")
            return []

    query = f"{song} {artist} {album}"
    print(f"Searching YouTube for: {query}")
    scored_results = search_and_score(query)

    if not scored_results:
        # Try a fallback search without the album name
        print("Primary search failed, trying fallback search...")
        fallback_query = f"{song} {artist}"
        scored_results = search_and_score(fallback_query)

    return scored_results


def sanitize_filename(name: str) -> str:
    """
    Remove or replace characters that are not allowed in filenames.
    """
    sanitized = re.sub(r'[<>:"/\\|?*]', ' ', name)
    # Collapse multiple spaces into one (optional, for neatness)
    sanitized = re.sub(r'\s{2,}', ' ', sanitized)
    sanitized = re.sub(r'\.{2,}', ' ', sanitized)
    sanitized = sanitized.strip(' .')
    return sanitized


def build_download_path(playlist_name, artist, album):
    """
    Build an absolute download path using `download_path` as the root.
    Returns: (destination_path, full_file_path)
    """
    playlist_name = sanitize_filename(playlist_name)
    artist = sanitize_filename(artist)
    album = sanitize_filename(album)

    # Prevent duplicates
    if playlist_name.lower() == album.lower():
        playlist_name = ""

    # Combine all parts
    parts = [p for p in [playlist_name, artist, album] if p]

    # Absolute path under the main download_path
    destination_path = os.path.join(download_path, *parts)
    return destination_path


def download_single_track(args):
    """Download a single track - designed for parallel execution"""

    def is_age_restricted_error(error):
        error_str = str(error).lower()
        age_indicators = [
            'age-restricted', 'confirm your age', 'sign in to confirm',
            'restricted content', 'login required', 'this video may be inappropriate',
            'content warning', 'age verification required', 'youtube account'
        ]
        return any(indicator in error_str for indicator in age_indicators)

    track, playlist_name, track_index, total_tracks = args
    track, playlist_name, track_index, total_tracks = args
    successful = 0
    failed = 0
    failed_track = None

    # Raw Spotify data with fallbacks
    raw_song = getattr(track, "name", "Unknown Title")
    raw_artist = getattr(track.artists[0], "name", "Unknown Artist") if getattr(track, "artists",
                                                                                None) else "Unknown Artist"
    raw_album = getattr(track.album, "name", "Unknown Album") if getattr(track, "album", None) else "Unknown Album"
    track_num = getattr(track, "track_number", None)

    # Sanitize for filesystem
    song = sanitize_filename(raw_song)
    artist = sanitize_filename(raw_artist)
    album = sanitize_filename(raw_album)

    # Track filename
    file_name = f"{track_num:02d} - {song}.mp3" if isinstance(track_num, int) and track_num > 0 else f"{song}.mp3"

    destination_path = build_download_path(playlist_name, artist, album)
    os.makedirs(destination_path, exist_ok=True)

    # Full file path
    full_destination = os.path.join(destination_path, file_name)

    # Skip if already downloaded
    if os.path.exists(full_destination):
        with lock:
            print(f"[{track_index}/{total_tracks}] Already downloaded: {raw_song} by {raw_artist}")
        return 1, 0, None

    # yt-dlp options per track
    ydl_local = dict(ydl_opts)
    ydl_local['outtmpl'] = os.path.join(destination_path, os.path.splitext(file_name)[0] + ".%(ext)s")

    with lock:
        print(f"[{track_index}/{total_tracks}] Downloading: {raw_song} by {raw_artist}")

    try:
        # Get multiple possible matches
        youtube_results = get_best_youtube_matches(track)
        if not youtube_results:
            with lock:
                print(f"[{track_index}/{total_tracks}] Could not find YouTube URL for {raw_song} by {raw_artist}")
            return 0, 1, f"{raw_song} by {raw_artist}"

        success = False
        download_error = None

        for candidate in youtube_results:
            youtube_url = candidate['url']
            try:
                with lock:
                    print(
                        f"[{track_index}/{total_tracks}] Trying: {candidate['title']} (Score: {candidate['score']:.2f})")

                # Test if we can extract info first to catch age restrictions earlier
                with yt_dlp.YoutubeDL(ydl_local) as ydl:
                    # Try to get info first to catch age restrictions
                    try:
                        info = ydl.extract_info(youtube_url, download=False)
                    except yt_dlp.utils.DownloadError as e:
                        if is_age_restricted_error(e):
                            with lock:
                                print(f"[{track_index}/{total_tracks}] Age-restricted video: {candidate['title']}")
                            continue  # try next candidate
                        else:
                            raise  # re-raise other errors

                    # If we get here, proceed with download
                    ydl.download([youtube_url])

                success = True
                break  # stop once it downloads successfully

            except yt_dlp.utils.DownloadError as e:
                download_error = e
                if is_age_restricted_error(e):
                    with lock:
                        print(f"[{track_index}/{total_tracks}] Age-restricted video: {candidate['title']}")
                    continue  # try the next result
                else:
                    with lock:
                        print(f"[{track_index}/{total_tracks}] Download error ({candidate['title']}): {e}")
                    continue
            except Exception as e:
                download_error = e
                with lock:
                    print(f"[{track_index}/{total_tracks}] Unexpected download error ({candidate['title']}): {e}")
                continue

        if not success:
            error_msg = f"[{track_index}/{total_tracks}] All candidates failed for {raw_song} by {raw_artist}"
            if download_error:
                error_msg += f" - Last error: {download_error}"
            with lock:
                print(error_msg)
            return 0, 1, f"{raw_song} by {raw_artist}"

        # Rename the downloaded file if yt-dlp changed it
        if not os.path.exists(full_destination):
            mp3s = [f for f in os.listdir(destination_path) if f.lower().endswith('.mp3')]
            if mp3s:
                newest = max((os.path.join(destination_path, f) for f in mp3s), key=os.path.getmtime)
                if newest != full_destination:
                    try:
                        os.rename(newest, full_destination)
                    except Exception as e:
                        with lock:
                            print(
                                f"[{track_index}/{total_tracks}] Warning: couldn't rename {newest} -> {full_destination}: {e}")

        # Tag MP3
        if os.path.exists(full_destination):
            try:
                audiofile = eyed3.load(full_destination)
                if audiofile is None:
                    with lock:
                        print(
                            f"[{track_index}/{total_tracks}] Warning: couldn't load mp3 for tagging: {full_destination}")
                    # Still count as successful since file exists
                    return 1, 0, None

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
                    with lock:
                        print(f"[{track_index}/{total_tracks}] Warning: couldn't get genre: {e}")

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
                    with lock:
                        print(f"[{track_index}/{total_tracks}] Warning: couldn't embed cover art: {e}")

                audiofile.tag.save()
                with lock:
                    print(f"[{track_index}/{total_tracks}] ✓ Success: {raw_song} by {raw_artist}")
                return 1, 0, None

            except Exception as e:
                with lock:
                    print(f"[{track_index}/{total_tracks}] Error tagging {full_destination}: {e}")
                # Still count as successful since download worked
                return 1, 0, None
        else:
            with lock:
                print(f"[{track_index}/{total_tracks}] Failed to find the downloaded file at: {full_destination}")
            return 0, 1, f"{raw_song} by {raw_artist}"

    except Exception as e:
        with lock:
            print(f"[{track_index}/{total_tracks}] Unexpected error for '{raw_song}' by '{raw_artist}': {e}")
        return 0, 1, f"{raw_song} by {raw_artist}"


def songs_downloader(playlist_name, tracks, parallel=True):
    """
    Download Spotify tracks as MP3s with optional parallel processing.
    """
    total_tracks = len(tracks)
    print(f"\nStarting download of {total_tracks} tracks from '{playlist_name}'")
    print(f"Parallel downloads: {parallel} (max workers: {max_workers})")

    if not parallel:
        # Sequential download (original behavior)
        successful = 0
        failed = 0
        failed_list = []

        for i, track in enumerate(tracks):
            s, f, failed_track = download_single_track((track, playlist_name, i + 1, total_tracks))
            successful += s
            failed += f
            if failed_track:
                failed_list.append(failed_track)
    else:
        # Parallel download
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Prepare arguments for each track
            args_list = [(track, playlist_name, i + 1, total_tracks) for i, track in enumerate(tracks)]

            # Submit all tasks
            future_to_track = {executor.submit(download_single_track, args): args for args in args_list}

            successful = 0
            failed = 0
            failed_list = []

            # Process completed tasks as they finish
            for future in concurrent.futures.as_completed(future_to_track):
                try:
                    s, f, failed_track = future.result()
                    successful += s
                    failed += f
                    if failed_track:
                        failed_list.append(failed_track)
                except Exception as exc:
                    failed += 1
                    failed_list.append(f"Unknown track - {exc}")
                    print(f'Generated an exception: {exc}')

    # Summary
    print("\n" + "=" * 50)
    print("DOWNLOAD SUMMARY:")
    print(f"Playlist: {playlist_name}")
    print(f"Successful: {successful}/{total_tracks}")
    print(f"Failed: {failed}/{total_tracks}")
    print(f"Success rate: {(successful / total_tracks) * 100:.1f}%")

    if failed_list:
        print("\nFailed tracks:")
        for failed_track in failed_list:
            print(f"  - {failed_track}")
    print("=" * 50)

    return successful, failed, failed_list


def _is_age_restricted_error(self, error):
    """
    Comprehensive age restriction error detection.
    """
    error_str = str(error).lower()
    age_indicators = [
        'age-restricted',
        'confirm your age',
        'sign in to confirm',
        'restricted content',
        'login required',
        'this video may be inappropriate',
        'content warning',
        'age verification required',
        'youtube account',
        'protected content'
    ]

    return any(indicator in error_str for indicator in age_indicators)


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


def configure_parallel_downloads():
    """Configure parallel download settings"""
    global max_workers
    print(f"\nCurrent parallel download settings:")
    print(f"Max parallel downloads: {max_workers}")
    print(f"Note: Higher numbers may cause rate limiting or performance issues")
    print(f"Recommended: 2-5 for most systems")

    try:
        new_workers = input(f"Enter new max parallel downloads [current: {max_workers}]: ").strip()
        if new_workers:
            new_workers = int(new_workers)
            if 1 <= new_workers <= 100:
                max_workers = new_workers
                print(f"Max parallel downloads set to: {max_workers}")
            else:
                print("Please enter a number between 1 and 10")
    except ValueError:
        print("Invalid input. Please enter a number.")


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
    print("11. Download liked songs")
    print("12. Configure parallel downloads")  # New option
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


def post_search_menu(query, results, parallel=True):
    print()
    print("1. Download songs from search results")
    print("2. Create playlist from search results")
    print("3. Exit")
    try:
        action = int(input("Enter option: "))
    except ValueError:
        print("Invalid input")
        return post_search_menu(query, results, parallel)

    if action == 1:
        # Choose songs to download
        songs_index = input("Enter songs number, 'all' for all, or multiple numbers separated by spaces: ")
        if songs_index.lower() == 'all':
            songs_downloader("Search Results", results, parallel=parallel)
        else:
            # Parse multiple indices
            songs_index = songs_index.replace(',', ' ').replace('.', ' ').replace('-', ' ').split()
            try:
                songs_index = [int(i) for i in songs_index]
                selected_tracks = [results[i] for i in songs_index if i < len(results)]
                songs_downloader("Selected Tracks", selected_tracks, parallel=parallel)
            except (ValueError, IndexError):
                print("Invalid song numbers. Please enter valid numbers.")
                return post_search_menu(query, results, parallel)

    elif action == 2:
        playlist = create_playlist(query, "Created by spotify-downloader")
        add_tracks_to_playlist(playlist, results)
        print("Playlist created: " + playlist.name)

    elif action == 3:
        return None

    else:
        print("Invalid input")
        return post_search_menu(query, results, parallel)

    return None


def main():
    global max_workers
    while True:
        action = menu()
        if action == 1:
            playlists = list_playlists()
            try:
                playlist_index = int(input("Enter playlist number: "))
                playlist = playlists.items[playlist_index]
                playlist_name = playlist.name
            except (ValueError, IndexError):
                print("Invalid playlist number. Try again.")
                continue

            # Ask about parallel download
            use_parallel = input("Use parallel downloads? (y/n) [default: y]: ").strip().lower()
            parallel = use_parallel != 'n'

            tracks = get_playlist_tracks(playlist)
            tracks = playlist_tracks_to_tracks(tracks)
            songs_downloader(playlist_name, tracks, parallel=parallel)

        elif action == 2:
            playlists = list_playlists()
            try:
                playlist_index = int(input("Enter playlist number: "))
                playlist = playlists.items[playlist_index]
                playlist_name = playlist.name
            except (ValueError, IndexError):
                print("Invalid playlist number. Try again.")
                continue

            # Ask about parallel download
            use_parallel = input("Use parallel downloads? (y/n) [default: y]: ").strip().lower()
            parallel = use_parallel != 'n'

            tracks = get_playlist_tracks(playlist)
            recommendations = get_recommendations(tracks)
            songs_downloader(playlist_name, recommendations, parallel=parallel)

        elif action == 3:
            # Ask about parallel download
            use_parallel = input("Use parallel downloads? (y/n) [default: y]: ").strip().lower()
            parallel = use_parallel != 'n'

            top_tracks = get_top_tracks(int(input("Enter number of top tracks: ")))
            playlist_name = "Top tracks"
            songs_downloader(playlist_name, top_tracks, parallel=parallel)

        elif action == 4:
            # Ask about parallel download
            use_parallel = input("Use parallel downloads? (y/n) [default: y]: ").strip().lower()
            parallel = use_parallel != 'n'

            top_tracks = get_top_tracks(int(input("Enter number of top tracks: ")))
            recommendations = get_recommendations(top_tracks)
            playlist_name = "Top tracks recommendations"
            songs_downloader(playlist_name, recommendations, parallel=parallel)

        elif action == 5:
            playlists = list_playlists()
            playlist = playlists.items[int(input("Enter playlist number: "))]
            tracks = get_playlist_tracks(playlist)
            recommendations = get_recommendations(tracks)
            playlist = create_playlist(playlist.name + " recommendations", "Recommended songs from " + playlist.name)
            add_tracks_to_playlist(playlist, recommendations)
            print(f"Playlist '{playlist.name}' created successfully!")

        elif action == 6:
            top_tracks = get_top_tracks()
            playlist = create_playlist("Top tracks", "Top tracks from user")
            add_tracks_to_playlist(playlist, top_tracks)
            print(f"Playlist '{playlist.name}' created successfully!")

        elif action == 7:
            top_tracks = get_top_tracks()
            recommendations = get_recommendations(top_tracks)
            playlist = create_playlist("Top tracks recommendations", "Recommended songs from top tracks")
            add_tracks_to_playlist(playlist, recommendations)
            print(f"Playlist '{playlist.name}' created successfully!")

        elif action == 8:
            search_result = search_menu()
            if search_result:
                query, results = search_result
                # Ask about parallel download for search results
                use_parallel = input("Use parallel downloads? (y/n) [default: y]: ").strip().lower()
                parallel = use_parallel != 'n'
                post_search_menu(query, results, parallel=parallel)

        elif action == 9:
            print("Goodbye!")
            exit()

        elif action == 10:
            choose_quality()

        elif action == 11:
            # Ask about parallel download
            use_parallel = input("Use parallel downloads? (y/n) [default: y]: ").strip().lower()
            parallel = use_parallel != 'n'

            liked_songs = list_liked_songs()
            liked_tracks = [item.track for item in liked_songs]
            playlist_name = "Liked songs"
            songs_downloader(playlist_name, liked_tracks, parallel=parallel)

        elif action == 12:
            configure_parallel_downloads()

        else:
            print("Invalid option. Please try again.")

        print()  # Add empty line for better readability


if __name__ == "__main__":
    main()
