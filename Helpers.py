import asyncio
import datetime
import re
import threading
import time
from datetime import timedelta
from http.client import InvalidURL
import random
from math import floor
from typing import Optional
from urllib.parse import parse_qs, urlparse
from typing import Optional, List 
import discord
import requests
from discord import VoiceClient, app_commands, Embed, VoiceProtocol
from discord.ext.commands import Cog, Bot

from Database import *
from yt_dlp import YoutubeDL
import validators


ydl_opts = {
    'default_search': 'ytsearch',
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'outtmpl': '%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'ignoreerrors': True,
    'socket_timeout': 60,
    'retries': 3
}

ydl_playlist_opts = {
    'default_search': 'ytsearch',
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'outtmpl': '%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'extract_flat': True,
    'quiet': True,
    'no_warnings': True,
    'ignoreerrors': True,
    'socket_timeout': 60,
    'retries': 3
}

ffmpeg_before_options = (
    "-reconnect 1 "
    "-reconnect_streamed 1 "
    "-reconnect_at_eof 1 "
    "-reconnect_delay_max 5 "
    "-timeout 30000000 "
    "-user_agent 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' "
    "-headers 'Accept-Language: en-US,en;q=0.9' "
    "-multiple_requests 1 "
    "-seekable 0"
)

ffmpeg_options = {
    'options': '-vn -bufsize 4096k -maxrate 512k',
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -use_wallclock_as_timestamps 1"
}


class UserNotInVoiceException(Exception):
    def __init__(self, msg: str = "Du bist in keinem Voice Channel"):
        super().__init__(msg)

class DifferentVoiceChannelException(Exception):
    def __init__(self, msg: str = "Du bist in einem anderen Voice Channel"):
        super().__init__(msg)

class BotNotInVoiceException(Exception):
    def __init__(self, msg: str = "Ich bin nicht in einem Voice Channel"):
        super().__init__(msg)

class PlaylistTooLargeException(Exception):
    def __init__(self, msg: str = "Playlist ist zu groß (Maximum 50 Songs)"):
        super().__init__(msg)

class VoteSkipPoll:
    def __init__(self, channel_members: int):
        self.votes_needed = max(2, channel_members // 2)  # At least 2 votes, or half the channel
        self.voted_users = set()
        self.created_at = time.time()
        
    def add_vote(self, user_id: int) -> bool:
        """Add a vote and return True if skip threshold is reached"""
        self.voted_users.add(user_id)
        return len(self.voted_users) >= self.votes_needed
        
    def get_progress(self) -> str:
        return f"{len(self.voted_users)}/{self.votes_needed}"
        
    def is_expired(self, timeout: int = 30) -> bool:
        """Check if poll has expired (default 30 seconds)"""
        return time.time() - self.created_at > timeout
    
class Getter:
    def __init__(self):
        self.db: Database = Database()
        self.yt = self.db.get_or_add_by_name(Platform, "Youtube")
        self.sc = self.db.get_or_add_by_name(Platform, "Soundcloud")
        self.yt_re = re.compile(r"^((?:https?:)?\/\/)?((?:www|m)\.)?((?:youtube(?:-nocookie)?\.com|youtu.be))(\/(?:[\w\-]+\?v=|embed\/|live\/|v\/)?)([\w\-]+)(\S+)?$")
        self.sc_re = re.compile(r"^((?:https?:)?\/\/)?((?:www|m)\.)?((?:soundcloud\.com))")
        
        self.yt_playlist_re = re.compile(r"^((?:https?:)?\/\/)?((?:www|m)\.)?((?:youtube(?:-nocookie)?\.com|youtu.be)).*[?&]list=([\w\-_]+)(&.*)?$")
        self.sc_playlist_re = re.compile(r"^((?:https?:)?\/\/)?((?:www|m)\.)?((?:soundcloud\.com)).*\/sets\/")

    def validate_yt_url(self, url: str) -> bool:
        return self.yt_re.match(url) is not None

    def validate_sc_url(self, url: str) -> bool:
        return self.sc_re.match(url) is not None
    
    def validate_yt_playlist_url(self, url: str) -> bool:
        """Enhanced YouTube playlist URL validation using URL parsing"""
        try:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            
            
            youtube_domains = ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtube-nocookie.com']
            is_youtube = any(domain in parsed_url.netloc.lower() for domain in youtube_domains)
            
            
            if 'youtu.be' in parsed_url.netloc.lower():
                is_youtube = True
            
           
            has_list = 'list' in query_params and query_params['list'][0]
            
            return is_youtube and has_list
        except Exception as e:
            print(f"Error validating YouTube playlist URL: {e}")
            return self.yt_playlist_re.match(url) is not None

    
    def validate_sc_playlist_url(self, url: str) -> bool:
        """Enhanced SoundCloud playlist URL validation"""
        try:
            parsed_url = urlparse(url)
            is_soundcloud = 'soundcloud.com' in parsed_url.netloc.lower()
            has_sets = '/sets/' in parsed_url.path
            return is_soundcloud and has_sets
        except Exception as e:
            print(f"Error validating SoundCloud playlist URL: {e}")
            
            return self.sc_playlist_re.match(url) is not None
        
    def is_playlist_url(self, url: str) -> bool:
        return self.validate_yt_playlist_url(url) or self.validate_sc_playlist_url(url)

    def log_to_file(self, message: str):
        with open("log.json", "w+") as f:
            f.write(str(message))

    def fetch_from_yt(self, name: str) -> Song:
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info("ytsearch:"+name, download=False)
                if not info or 'entries' not in info or not info['entries']:
                    raise Exception(f"No results found for: {name}")
                
                entry = info['entries'][0]
                artist = self.db.get_or_add_by_name(Artist, entry.get('channel', 'Unknown'))
                song = Song(
                    name=entry['title'], 
                    url=entry['webpage_url'], 
                    duration=entry.get('duration', 0), 
                    artists=artist, 
                    stream_url=entry['url'], 
                    platforms=self.yt
                )
                self.db.add(Song, song)
                return song
        except Exception as e:
            print(f"Error fetching from YouTube: {e}")
            raise
        
    def fetch_from_sc(self, name: str) -> Song:
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info("scsearch:"+name, download=False)
                if not info or 'entries' not in info or not info['entries']:
                    raise Exception(f"No results found for: {name}")
                
                entry = info['entries'][0]
                artist = self.db.get_or_add_by_name(Artist, entry.get('artist', 'Unknown'))
                song = Song(
                    name=entry['title'], 
                    url=entry['webpage_url'], 
                    duration=entry.get('duration', 0), 
                    artists=artist, 
                    stream_url=entry['url'], 
                    platforms=self.sc
                )
                self.db.add(Song, song)
                return song
        except Exception as e:
            print(f"Error fetching from SoundCloud: {e}")
            raise
        
    def fetch_playlist_from_url(self, url: str, max_songs: int = 50) -> List[Song]:
        """Fetch songs from a playlist URL"""
        try:
            # Updated yt-dlp options for playlist extraction
            playlist_opts = {
                'format': 'bestaudio/best',
                'extractaudio': True,
                'audioformat': 'mp3',
                'outtmpl': '%(title)s.%(ext)s',
                'restrictfilenames': True,
                'noplaylist': False,  # Important: Allow playlist extraction
                'extract_flat': True,  # Get metadata without downloading
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,  # Continue on errors
                'playlistend': max_songs,  # Limit playlist size
            }

            print(f"Attempting to extract playlist from: {url}")
            
            # Extract playlist info
            with YoutubeDL(playlist_opts) as ydl:
                try:
                    playlist_info = ydl.extract_info(url, download=False)
                except Exception as e:
                    print(f"Initial extraction failed: {e}")
                    # Try without extract_flat for problematic playlists
                    playlist_opts['extract_flat'] = False
                    playlist_info = ydl.extract_info(url, download=False)

                if not playlist_info:
                    raise Exception("Could not extract playlist information")

                print(f"Playlist info keys: {playlist_info.keys()}")
                
                # Handle different playlist structures
                entries = []
                
                # Check if it's a direct playlist
                if 'entries' in playlist_info and playlist_info['entries']:
                    entries = playlist_info['entries']
                    print(f"Found {len(entries)} entries in playlist")
                
                # Check if it's a single video that's part of a playlist
                elif 'playlist' in playlist_info and playlist_info.get('playlist'):
                    # Try to get the full playlist
                    playlist_id = None
                    parsed_url = urlparse(url)
                    query_params = parse_qs(parsed_url.query)
                    
                    if 'list' in query_params:
                        playlist_id = query_params['list'][0]
                        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
                        print(f"Extracting full playlist: {playlist_url}")
                        
                        # Extract the full playlist
                        full_playlist_info = ydl.extract_info(playlist_url, download=False)
                        if full_playlist_info and 'entries' in full_playlist_info:
                            entries = full_playlist_info['entries']
                            print(f"Found {len(entries)} entries in full playlist")
                
                # If still no entries, try alternative approach
                if not entries:
                    print("No entries found, trying alternative extraction...")
                    
                    # Parse playlist ID from URL
                    parsed_url = urlparse(url)
                    query_params = parse_qs(parsed_url.query)
                    
                    if 'list' in query_params:
                        playlist_id = query_params['list'][0]
                        
                        # Try different playlist URL formats
                        playlist_urls = [
                            f"https://www.youtube.com/playlist?list={playlist_id}",
                            f"https://youtube.com/playlist?list={playlist_id}",
                            f"https://www.youtube.com/watch?list={playlist_id}",
                        ]
                        
                        for playlist_url in playlist_urls:
                            try:
                                print(f"Trying playlist URL: {playlist_url}")
                                alt_info = ydl.extract_info(playlist_url, download=False)
                                if alt_info and 'entries' in alt_info and alt_info['entries']:
                                    entries = alt_info['entries']
                                    print(f"Success! Found {len(entries)} entries")
                                    break
                            except Exception as e:
                                print(f"Failed with URL {playlist_url}: {e}")
                                continue

                if not entries:
                    raise Exception("No playlist entries found. This might be a single video or an invalid playlist.")

                # Filter out None entries and limit count
                entries = [entry for entry in entries if entry is not None]
                if len(entries) > max_songs:
                    entries = entries[:max_songs]
                    print(f"Playlist truncated to {max_songs} songs")

                songs = []
                platform = self.yt if self.validate_yt_playlist_url(url) else self.sc

                print(f"Processing {len(entries)} playlist entries...")

                # Process each entry
                for i, entry in enumerate(entries):
                    try:
                        if entry is None:
                            print(f"Skipping entry {i+1}: Entry is None")
                            continue

                        # Get video URL
                        video_url = None
                        if entry.get('webpage_url'):
                            video_url = entry['webpage_url']
                        elif entry.get('url'):
                            video_url = entry['url']
                        elif entry.get('id') and platform == self.yt:
                            video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                        else:
                            print(f"Skipping entry {i+1}: No valid URL found")
                            continue

                        # Check if song already exists
                        existing_song = self.db.get_by_url(Song, video_url)
                        if existing_song:
                            songs.append(existing_song)
                            print(f"Found existing song {i+1}/{len(entries)}: {existing_song.name}")
                            continue

                        # For flat extraction, we need to get full info
                        if playlist_opts.get('extract_flat', False):
                            # Extract full info for this video
                            single_opts = {
                                'format': 'bestaudio/best',
                                'quiet': True,
                                'no_warnings': True,
                            }
                            
                            with YoutubeDL(single_opts) as single_ydl:
                                video_info = single_ydl.extract_info(video_url, download=False)
                        else:
                            video_info = entry

                        if not video_info:
                            print(f"Skipping entry {i+1}: Could not extract video info")
                            continue

                        # Get artist name
                        if platform == self.yt:
                            artist_name = video_info.get('channel', video_info.get('uploader', 'Unknown'))
                        else:
                            artist_name = video_info.get('artist', video_info.get('uploader', 'Unknown'))
                        
                        artist = self.db.get_or_add_by_name(Artist, artist_name)

                        # Create song object
                        song = Song(
                            name=video_info.get('title', f'Unknown Song {i+1}'),
                            url=video_info.get('webpage_url', video_url),
                            duration=video_info.get('duration', 0),
                            artists=artist,
                            stream_url=video_info.get('url', ''),
                            platforms=platform
                        )
                        
                        self.db.add(Song, song)
                        songs.append(song)
                        print(f"Added song {i+1}/{len(entries)}: {song.name}")

                    except Exception as e:
                        print(f"Error processing playlist entry {i+1}: {e}")
                        continue

                if not songs:
                    raise Exception("No valid songs could be extracted from the playlist")

                print(f"Successfully processed {len(songs)} songs from playlist")
                return songs

        except Exception as e:
            print(f"Error fetching playlist from URL {url}: {e}")
            raise
        
    def fetch_from_url(self, url: str) -> Song:
        existing_song = self.db.get_by_url(Song, url)
        if existing_song:
            return existing_song

        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise InvalidURL("Invalid URL")

                artist = None
                platform = None
                
                if self.validate_yt_url(url):
                    artist = self.db.get_or_add_by_name(Artist, info.get('channel', 'Unknown'))
                    platform = self.yt
                elif self.validate_sc_url(url):
                    artist = self.db.get_or_add_by_name(Artist, info.get('artist', 'Unknown'))
                    platform = self.sc
                else:
                    artist = self.db.get_or_add_by_name(Artist, info.get('uploader', 'Unknown'))
                    platform = self.yt  
                
                song = Song(
                    name=info['title'], 
                    url=info['webpage_url'], 
                    duration=info.get('duration', 0), 
                    artists=artist, 
                    stream_url=info['url'], 
                    platforms=platform
                )
                self.db.add(Song, song)
                return song
        except Exception as e:
            print(f"Error fetching from URL {url}: {e}")
            raise

    def get_song_by_name(self, name: str) -> Song:
        db_song = self.db.get_by_name(Song, name)
        if db_song:
            return db_song
        else:
            return self.fetch_from_yt(name)


    def get_songs_by_name(self, names: List[str]) -> List[Song]:
        songs: List[Song] = []
        for name in names:
            try:
                db_song = self.db.get_by_name(Song, name)
                if db_song:
                    songs.append(db_song)
                else:
                    song = self.fetch_from_yt(name)
                    songs.append(song)
            except Exception as e:
                print(f"Error getting song {name}: {e}")
                continue
        return songs

    def get_song_by_url(self, url: str) -> Song:
        db_song = self.db.get_by_url(Song, url)
        if db_song:
            return db_song
        else:
            return self.fetch_from_url(url)

    def reload_stream_url(self, song: Song) -> Song:
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(song.url, download=False)
                song.stream_url = info['url']
                self.db.update(Song, song)
            return song
        except Exception as e:
            print(f"Error reloading stream URL for {song.name}: {e}")
            return song

    def get_stream_url_with_time(self, song: Song, time: int) -> Song:
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(song.url, download=False)
                song.stream_url = info['url'] + "?p=" + str(floor(time))
            return song
        except Exception as e:
            print(f"Error getting stream URL with time for {song.name}: {e}")
            return song




class Manager(Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.queue: List[Song] = []
        self.current_song: Song = None
        self.previous_song: Song = None  # NEW: Track previous song for rewind
        self.voice_client: VoiceClient = None
        self.getter: Getter = Getter()
        self.song_playing_since: Optional[float] = None
        self.is_playing_flag: bool = False
        self.is_paused: bool = False  # NEW: Track pause state
        self.pause_time: Optional[float] = None  # NEW: Track when paused
        self.play_lock = asyncio.Lock()
        self.active_poll_message: Optional[discord.Message] = None

    def next_song(self):
        if len(self.queue) > 0:
            self.previous_song = self.current_song  # NEW: Store previous song
            self.current_song = self.queue.pop(0)
        else:
            self.previous_song = self.current_song  # NEW: Store previous song
            self.current_song = None

    def add_to_queue(self, song: Song) -> bool:
        self.queue.append(song)
        return True
    
    def add_songs_to_queue(self, songs: List[Song]) -> int:
        """Add multiple songs to queue and return count"""
        for song in songs:
            self.queue.append(song)
        return len(songs)

    def remove_from_queue(self, song: Song) -> bool:
        if song in self.queue:
            self.queue.remove(song)
            return True
        else:
            return False

    def clear_queue(self) -> bool:
        self.queue.clear()
        return True

    def duration(self):
        i = 0
        for song in self.queue:
            i += song.duration
        return i

    def get_queue(self) -> List[Song]:
        return self.queue

    def get_current_song(self) -> Optional[Song]:
        return self.current_song

    def is_playing(self) -> bool:
        return (self.voice_client and self.voice_client.channel and self.voice_client.source and self.current_song is not None)

    def get_voice_client(self) -> Optional[VoiceClient]:
        return self.voice_client

    def is_connected(self) -> bool:
        return self.voice_client and self.voice_client.is_connected()

    # NEW: Method to move song to front of queue
    def move_to_next(self, song_index: int) -> bool:
        """Move a song from the queue to be played next"""
        if 0 <= song_index < len(self.queue):
            song = self.queue.pop(song_index)
            self.queue.insert(0, song)
            return True
        return False
    
    async def _disconnect(self) -> bool:
        if self.voice_client.is_connected():
            await self.voice_client.disconnect()
            self.voice_client = None
            self.queue.clear()
            self.current_song = None
            return True
        else:
            raise BotNotInVoiceException()

    async def connect_to_channel(self, channel: discord.VoiceChannel) -> bool:
        if not self.voice_client:
            self.voice_client = await channel.connect()
            return True
        else:
            if self.voice_client.channel != channel:
                if len(self.voice_client.channel.members) == 1:
                    await self.voice_client.move_to(channel)
                    return True
                else:
                    raise DifferentVoiceChannelException("Ich bin bereits in einem anderen Channel")
            else:
                return True

    async def set_status(self):
        try:
            if self.current_song:
                await self.bot.change_presence(activity=discord.Game(name=self.current_song.name))
            else:
                await self.bot.change_presence(activity=discord.Game(name="Nix"))
        except Exception as e:
            print(f"Error setting status: {e}")
            
    async def _play(self, error=None):
        async with self.play_lock:
            self.song_playing_since = None
            self.is_playing_flag = False
            self.is_paused = False
            
            if error:
                print(f"Error playing song: {error}")

            # Check if we're still connected
            if not self.voice_client or not self.voice_client.is_connected():
                print("Voice client not connected, stopping playback")
                return

            self.next_song()
            if self.current_song is None:
                print("Queue leer – nichts mehr zu spielen.")
                await self.set_status()
                try:
                    await self.voice_client.disconnect()
                except Exception as e:
                    print(f"Fehler beim Trennen vom Voice-Channel: {e}")
                return


            print(f"Playing: {self.current_song.name}")
            
            # Try to play the song with retry mechanism
            for attempt in range(3):
                try:
                    # Check stream URL validity
                    stream_url = self.current_song.stream_url
                    
                    # Test if stream URL is still valid
                    try:
                        head = requests.head(stream_url, allow_redirects=True, timeout=10)
                        if head.status_code == 403 or head.status_code >= 400:
                            print(f"Stream URL invalid (status {head.status_code}), reloading...")
                            self.current_song = self.getter.reload_stream_url(self.current_song)
                            stream_url = self.current_song.stream_url
                    except requests.RequestException as e:
                        print(f"Error checking stream URL, reloading: {e}")
                        self.current_song = self.getter.reload_stream_url(self.current_song)
                        stream_url = self.current_song.stream_url
                    
                    # Create audio source
                    source = discord.FFmpegPCMAudio(stream_url, **ffmpeg_options)
                    
                    # Check if still connected before playing
                    if not self.voice_client.is_connected():
                        print("Lost connection while preparing to play")
                        return
                    
                    await self.set_status()
                    
                    self.song_playing_since = time.time()
                    self.is_playing_flag = True
                    self.reconnect_attempts = 0  # Reset reconnect attempts on successful play
                    
                    def after_playing(err):
                        print("after_playing wurde aufgerufen.")
                        if err:
                            print(f"Player error: {err}")
                        # Check if we're still connected before continuing
                        if self.voice_client and self.voice_client.is_connected():
                            asyncio.run_coroutine_threadsafe(self._play(), self.bot.loop)
                        else:
                            print("Not connected after song finished, stopping playback")
                    
                    self.voice_client.play(source, after=after_playing)
                    return  # Successfully started playing
                    
                except Exception as e:
                    print(f"Error in _play attempt {attempt + 1}: {e}")
                    if attempt == 2:  # Last attempt
                        print("All play attempts failed, trying next song")
                        if self.queue:
                            asyncio.run_coroutine_threadsafe(self._play(), self.bot.loop)
                        return
                    
                    # Wait before retry
                    await asyncio.sleep(2)


    def get_voice_client_on_reload(self):
        vcs = self.bot.voice_clients
        return vcs[0] if vcs else None

    async def cog_load(self):
        if not self.voice_client and self.get_voice_client_on_reload():
            self.voice_client = self.get_voice_client_on_reload()
            dummy_song = self.getter.db.get_dummy(Song)
            if dummy_song:
                self.current_song = dummy_song
        print("Manager cog loaded, syncing commands...")
                
    # Event handlers for voice connection issues
    @Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member == self.bot.user:
            if before.channel and not after.channel:
                print("Bot was disconnected from voice channel")
                self.voice_client = None
                self.current_song = None
                self.previous_song = None  # NEW: Clear previous song
                self.queue.clear()
                self.is_paused = False  # NEW: Reset pause state
                self.active_poll_message = None
                await self.set_status()


    @app_commands.command(name="play", description="Play a song")
    @app_commands.describe(song="Name or URL of the song")
    async def play(self, interaction: discord.Interaction, *, song: str):
        await interaction.response.defer()
        
        try:
            if not interaction.user.voice:
                raise UserNotInVoiceException()
            
            if not self.voice_client:
                await self.connect_to_channel(interaction.user.voice.channel)
            
            if self.voice_client.channel != interaction.user.voice.channel:
                raise DifferentVoiceChannelException()

            #Playlist or Single Song
            if validators.url(song) and self.getter.is_playlist_url(song):
                await interaction.followup.send("🎵 Playlist erkannt! Lade Songs...")
                
                try:
                    songs = self.getter.fetch_playlist_from_url(song)
                    if not songs:
                        await interaction.followup.send("❌ Keine Songs in der Playlist gefunden")
                        return
                    
                    added_count = self.add_songs_to_queue(songs)
                    
                    # Start playing if not already playing
                    if not self.is_playing():
                        await self._play()
                    
                    await interaction.followup.send(
                        f"✅ **{added_count}** Songs aus der Playlist zur Warteschlange hinzugefügt!\n"
                        f"Erste Songs: {', '.join([s.name[:30] + '...' if len(s.name) > 30 else s.name for s in songs[:3]])}"
                        + (f" und {len(songs) - 3} weitere..." if len(songs) > 3 else "")
                    )
                    
                except PlaylistTooLargeException as e:
                    await interaction.followup.send(f"❌ {str(e)}")
                except Exception as e:
                    await interaction.followup.send(f"❌ Fehler beim Laden der Playlist: {str(e)}")
            
            else:
                #One Song
                if validators.url(song):
                    song_obj = self.getter.get_song_by_url(song)
                else:
                    song_obj = self.getter.get_song_by_name(song)

                self.add_to_queue(song_obj)
                song_name = song_obj.name
                
            
                if not self.is_playing():
                    await self._play()
                
                await interaction.followup.send(f"**{song_name}** zur Warteschlange hinzugefügt")
            
        except Exception as e:
            await interaction.followup.send(f"Fehler: {str(e)}")
            
            
    @app_commands.command(name="playlist", description="Add a playlist to the queue")
    @app_commands.describe(
        url="Playlist URL (YouTube or SoundCloud)",
        max_songs="Maximum number of songs to add (default: 100)"
    )
    async def playlist(self, interaction: discord.Interaction, url: str, max_songs: int = 100):
        await interaction.response.defer()
        
        try:
            if not interaction.user.voice:
                raise UserNotInVoiceException()
            
            if not self.voice_client:
                await self.connect_to_channel(interaction.user.voice.channel)
            
            if self.voice_client.channel != interaction.user.voice.channel:
                raise DifferentVoiceChannelException()

            if not validators.url(url):
                await interaction.followup.send("❌ Bitte gib eine gültige URL ein")
                return

            if not self.getter.is_playlist_url(url):
                await interaction.followup.send("❌ Die URL ist keine gültige Playlist")
                return

            # Limit max_songs
            max_songs = min(max_songs, 200)  
            
            await interaction.followup.send(f"🎵 Lade Playlist... (max. {max_songs} Songs)")
            
            songs = self.getter.fetch_playlist_from_url(url, max_songs)
            if not songs:
                await interaction.followup.send("❌ Keine Songs in der Playlist gefunden")
                return
            
            added_count = self.add_songs_to_queue(songs)
            
            # Start playing if not already playing
            if not self.is_playing():
                await self._play()
            
            # Create embed with playlist info
            embed = Embed(
                title="🎵 Playlist hinzugefügt",
                description=f"**{added_count}** Songs zur Warteschlange hinzugefügt",
                color=0x00FF00
            )
            
            # Show first few songs
            song_list = []
            for i, song in enumerate(songs[:5]):
                duration_str = str(timedelta(seconds=int(song.duration))) if song.duration else "?"
                song_list.append(f"`{i+1}.` {song.name[:40]}{'...' if len(song.name) > 40 else ''} ({duration_str})")
            
            if song_list:
                embed.add_field(
                    name="Songs",
                    value="\n".join(song_list) + (f"\n... und {len(songs) - 5} weitere" if len(songs) > 5 else ""),
                    inline=False
                )
            
            total_duration = sum(song.duration for song in songs if song.duration)
            if total_duration:
                embed.add_field(
                    name="Gesamtdauer",
                    value=str(timedelta(seconds=int(total_duration))),
                    inline=True
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Fehler: {str(e)}")
            
    @app_commands.command(name="pause", description="Pause or resume the current song")
    async def pause(self, interaction: discord.Interaction):
        try:
            if not self.voice_client:
                raise BotNotInVoiceException()
            if not interaction.user.voice or interaction.user.voice.channel != self.voice_client.channel:
                raise DifferentVoiceChannelException()

            if not self.is_playing():
                await interaction.response.send_message("Ich spiele gerade nichts")
                return

            if self.voice_client.is_paused():
                self.voice_client.resume()
                self.is_paused = False
                # Adjust the playing time to account for pause duration
                if self.pause_time and self.song_playing_since:
                    pause_duration = time.time() - self.pause_time
                    self.song_playing_since += pause_duration
                self.pause_time = None
                await interaction.response.send_message("▶️ Song fortgesetzt")
            else:
                self.voice_client.pause()
                self.is_paused = True
                self.pause_time = time.time()
                await interaction.response.send_message("⏸️ Song pausiert")
                
        except Exception as e:
            await interaction.response.send_message(f"Fehler: {str(e)}")

    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        try:
            if not self.voice_client:
                raise BotNotInVoiceException()
            if not interaction.user.voice or interaction.user.voice.channel != self.voice_client.channel:
                raise DifferentVoiceChannelException()

            if self.is_playing():
                self.voice_client.stop()
                await interaction.response.send_message("Song geskippt")
            else:
                await interaction.response.send_message("Ich spiele nichts")
        except Exception as e:
            await interaction.response.send_message(f"Fehler: {str(e)}")

    @app_commands.command(name="back", description="Play the previous song again")
    async def back(self, interaction: discord.Interaction):
        try:
            if not self.voice_client:
                raise BotNotInVoiceException()
            if not interaction.user.voice or interaction.user.voice.channel != self.voice_client.channel:
                raise DifferentVoiceChannelException()

            if not self.previous_song:
                await interaction.response.send_message("Kein vorheriger Song verfügbar")
                return

            
            self.queue.insert(0, self.previous_song)
            if self.is_playing():
                self.voice_client.stop()
                await interaction.response.send_message(f"⏮️ Spiele vorherigen Song: **{self.previous_song.name}**")
            else:
                await self._play()
                await interaction.response.send_message(f"▶️ Spiele vorherigen Song: **{self.previous_song.name}**")

        except Exception as e:
            await interaction.response.send_message(f"Fehler: {str(e)}")
            
    @app_commands.command(name="voteskip", description="Start a vote to skip the current song")
    async def voteskip(self, interaction: discord.Interaction):
        try:
            if not self.voice_client:
                raise BotNotInVoiceException()
            if not interaction.user.voice or interaction.user.voice.channel != self.voice_client.channel:
                raise DifferentVoiceChannelException()

            if not self.is_playing():
                await interaction.response.send_message("Ich spiele gerade nichts")
                return

            # Count non-bot members in voice channel
            channel_members = len([m for m in self.voice_client.channel.members if not m.bot])
            
            # If only one person (or less), skip immediately
            if channel_members <= 1:
                self.voice_client.stop()
                await interaction.response.send_message("🎵 Song geskippt")
                return

            # Check if there's already an active poll
            if self.active_poll_message:
                await interaction.response.send_message("Es läuft bereits eine Abstimmung zum Skippen!")
                return

            # Create poll with duration in HOURS (minimum 1 hour for Discord polls)
            # Since Discord requires minimum 1 hour, we'll use a different approach
            poll = discord.Poll(
                question=f"Skip '{self.current_song.name}'?",
                duration=timedelta(hours=1)  # Changed from seconds=30 to hours=1
            )
            poll.add_answer(text="✅ Ja", emoji="✅")
            poll.add_answer(text="❌ Nein", emoji="❌")

            await interaction.response.send_message(
                f"🗳️ **Vote Skip gestartet!**\n"
                f"Aktueller Song: **{self.current_song.name}**\n"
                f"Mehr als 50% der {channel_members} Mitglieder müssen für 'Ja' stimmen.\n"
                f"⏰ Abstimmung läuft für 30 Sekunden.",
                poll=poll
            )
            
            # Store the poll message
            self.active_poll_message = await interaction.original_response()
            
            # Start background task to check poll results (still check after 30 seconds)
            asyncio.create_task(self._monitor_poll(self.active_poll_message, channel_members))

        except Exception as e:
            await interaction.response.send_message(f"Fehler: {str(e)}")

    async def _monitor_poll(self, poll_message: discord.Message, total_members: int):
        """Monitor the poll and skip song if majority votes yes"""
        try:
            # Wait for 30 seconds (our custom timeout)
            await asyncio.sleep(30)
            
            # Fetch updated message to get poll results
            try:
                updated_message = await poll_message.fetch()
            except discord.NotFound:
                # Message was deleted
                self.active_poll_message = None
                return
            
            if not updated_message.poll:
                self.active_poll_message = None
                return
                
            poll = updated_message.poll
            
            # Find yes and no answers
            yes_votes = 0
            no_votes = 0
            
            for answer in poll.answers:
                if "✅" in answer.text or "Ja" in answer.text:
                    yes_votes = answer.vote_count
                elif "❌" in answer.text or "Nein" in answer.text:
                    no_votes = answer.vote_count
            
            total_votes = yes_votes + no_votes
            
            # Check if more than 50% voted yes
            if total_votes > 0 and yes_votes > (total_members / 2):
                # Skip the song
                if self.voice_client and self.is_playing():
                    self.voice_client.stop()
                    await poll_message.reply("🎵 **Vote Skip erfolgreich!** Song wird geskippt.")
                else:
                    await poll_message.reply("🎵 Vote Skip erfolgreich, aber es spielt bereits kein Song mehr.")
            else:
                await poll_message.reply(f"🎵 **Vote Skip fehlgeschlagen.** ({yes_votes}/{total_members} für Ja)")
            
            # Clear the active poll
            self.active_poll_message = None
            
            # End the poll manually by editing the message
            try:
                # Unfortunately, we can't end Discord polls programmatically
                # The poll will continue for the full hour, but we've already processed the results
                pass
            except Exception as e:
                print(f"Could not end poll early: {e}")
            
        except Exception as e:
            print(f"Error monitoring poll: {e}")
            self.active_poll_message = None
            
    @app_commands.command(name="stop", description="Stop the current song")
    async def stop(self, interaction: discord.Interaction):
        try:
            if not self.voice_client:
                raise BotNotInVoiceException()
            if not interaction.user.voice or interaction.user.voice.channel != self.voice_client.channel:
                raise DifferentVoiceChannelException()

            if self.is_playing():
                self.current_song = None
                self.queue.clear()
                self.voice_client.stop()
                await self.set_status()
                await interaction.response.send_message("Halt Stopp")
            else:
                await interaction.response.send_message("Ich spiele nichts")
        except Exception as e:
            await interaction.response.send_message(f"Fehler: {str(e)}")

    @app_commands.command(name="queue", description="Show the current queue")
    @app_commands.describe(page="Page number of the queue")
    async def queue(self, interaction: discord.Interaction, page: int = 1):
        try:
            if not self.voice_client:
                raise BotNotInVoiceException()
            if not interaction.user.voice or interaction.user.voice.channel != self.voice_client.channel:
                raise DifferentVoiceChannelException()
            
            page = max(1, page)
            start = (page - 1) * 15
            end = start + 15
            queue_text = ''
            
            current_queue = self.get_queue()
            if not current_queue:
                await interaction.response.send_message("Die Warteschlange ist leer")
                return
            
            for i, song in enumerate(current_queue[start:end], start=start):
                duration_str = str(timedelta(seconds=int(song.duration))) if song.duration else "Unknown"
                queue_text += f'`{i + 1}.` [**{song.name}**]({song.url}) - {duration_str}\n'
            
            total_pages = (len(current_queue) - 1) // 15 + 1
            embed = Embed(
                colour=0x00FF00,
                title="Warteschlange",
                description=f'**{len(current_queue)} tracks**\nGesamtdauer: {timedelta(seconds=self.duration())}\n\n{queue_text}'
            )
            embed.set_footer(text=f'Seite {page} von {total_pages}')
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(f"Fehler: {str(e)}")

    @app_commands.command(name="disconnect", description="Verlasse den Voice Channel")
    async def disconnect(self, interaction: discord.Interaction):
        try:
            if not self.voice_client:
                raise BotNotInVoiceException()
            if not interaction.user.voice or interaction.user.voice.channel != self.voice_client.channel:
                raise DifferentVoiceChannelException()

            await self._disconnect()
            await interaction.response.send_message("Voice Channel verlassen")
        except Exception as e:
            await interaction.response.send_message(f"Fehler: {str(e)}")

    @app_commands.command(name="clear", description="Lösche die Warteschlange")
    async def clear(self, interaction: discord.Interaction):
        try:
            if not self.voice_client:
                raise BotNotInVoiceException()
            if not interaction.user.voice or interaction.user.voice.channel != self.voice_client.channel:
                raise DifferentVoiceChannelException()

            self.clear_queue()
            await interaction.response.send_message("Warteschlange gelöscht")
        except Exception as e:
            await interaction.response.send_message(f"Fehler: {str(e)}")

    @app_commands.command(name="now", description="Zeige den aktuellen Song")
    async def now(self, interaction: discord.Interaction):
        try:
            if not self.voice_client:
                raise BotNotInVoiceException()
            if not interaction.user.voice or interaction.user.voice.channel != self.voice_client.channel:
                raise DifferentVoiceChannelException()

            if self.is_playing() and self.current_song:
                duration_str = str(timedelta(seconds=int(self.current_song.duration))) if self.current_song.duration else "Unknown"
                elapsed = int(time.time() - self.song_playing_since) if self.song_playing_since else 0
                elapsed_str = str(timedelta(seconds=elapsed))
                
                embed = Embed(
                    title="Aktuell spielt",
                    description=f"[**{self.current_song.name}**]({self.current_song.url})",
                    colour=0x00FF00
                )
                embed.add_field(name="Dauer", value=duration_str, inline=True)
                embed.add_field(name="Verstrichene Zeit", value=elapsed_str, inline=True)
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("Ich spiele nichts")
        except Exception as e:
            await interaction.response.send_message(f"Fehler: {str(e)}")


    @app_commands.command(name="shuffle", description="Mische die Warteschlange")
    async def shuffle(self, interaction: discord.Interaction):
        try:
            if not self.voice_client:
                raise BotNotInVoiceException()
            if not interaction.user.voice or interaction.user.voice.channel != self.voice_client.channel:
                raise DifferentVoiceChannelException()

            if not self.queue:
                await interaction.response.send_message("Die Warteschlange ist leer")
                return
                
            random.shuffle(self.queue)
            await interaction.response.send_message("Warteschlange gemischt")
        except Exception as e:
            await interaction.response.send_message(f"Fehler: {str(e)}")
            
    @app_commands.command(name="next", description="Move a song from the queue to play next")
    @app_commands.describe(position="Position of the song in the queue (1-based)")
    async def next(self, interaction: discord.Interaction, position: int):
        try:
            if not self.voice_client:
                raise BotNotInVoiceException()
            if not interaction.user.voice or interaction.user.voice.channel != self.voice_client.channel:
                raise DifferentVoiceChannelException()

            if not self.queue:
                await interaction.response.send_message("Die Warteschlange ist leer")
                return

            # Convert to 0-based index
            song_index = position - 1
            
            if song_index < 0 or song_index >= len(self.queue):
                await interaction.response.send_message(f"Ungültige Position. Warteschlange hat {len(self.queue)} Songs")
                return

            # Get the song before moving it
            song_to_move = self.queue[song_index]
            
            # Move the song to next position
            if self.move_to_next(song_index):
                embed = Embed(
                    title="⏭️ Song verschoben",
                    description=f"**{song_to_move.name}** wird als nächstes gespielt",
                    colour=0x00FF00
                )
                embed.add_field(
                    name="Vorherige Position",
                    value=f"#{position}",
                    inline=True
                )
                embed.add_field(
                    name="Neue Position",
                    value="#1 (Nächster Song)",
                    inline=True
                )
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("Fehler beim Verschieben des Songs")

        except Exception as e:
            await interaction.response.send_message(f"Fehler: {str(e)}")