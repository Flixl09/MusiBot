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
    'no_warnings': True
}

ffmpeg_before_options = (
    "-reconnect 1 "
    "-reconnect_streamed 1 "
    "-reconnect_at_eof 1 "
    "-reconnect_delay_max 5 "
    "-timeout 10000000 "
    "-user_agent 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'"
)
ffmpeg_options = {
    'options': '-vn -bufsize 1024k',
    'before_options': ffmpeg_before_options
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

class Getter:
    def __init__(self):
        self.db: Database = Database()
        self.yt = self.db.get_or_add_by_name(Platform, "Youtube")
        self.sc = self.db.get_or_add_by_name(Platform, "Soundcloud")
        self.yt_re = re.compile(r"^((?:https?:)?\/\/)?((?:www|m)\.)?((?:youtube(?:-nocookie)?\.com|youtu.be))(\/(?:[\w\-]+\?v=|embed\/|live\/|v\/)?)([\w\-]+)(\S+)?$")
        self.sc_re = re.compile(r"^((?:https?:)?\/\/)?((?:www|m)\.)?((?:soundcloud\.com))")

    def validate_yt_url(self, url: str) -> bool:
        return self.yt_re.match(url) is not None

    def validate_sc_url(self, url: str) -> bool:
        return self.sc_re.match(url) is not None

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
                    # Generic fallback
                    artist = self.db.get_or_add_by_name(Artist, info.get('uploader', 'Unknown'))
                    platform = self.yt  # Default to YouTube platform
                
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
        self.voice_client: VoiceClient = None
        self.getter: Getter = Getter()
        self.tree = bot.tree
        self.song_playing_since: Optional[float] = None
        self.is_playing_flag: bool = False
        self.play_lock = asyncio.Lock()

    def next(self):
        if len(self.queue) > 0:
            self.current_song = self.queue.pop(0)
        else:
            self.current_song = None

    def add_to_queue(self, song: Song) -> bool:
        self.queue.append(song)
        return True

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
            
            if error:
                print(f"Error playing song: {error}")

            self.next()
            if self.current_song is None:
                await self.set_status()
                return

            print(f"Playing: {self.current_song.name}")
            
            try:
                stream = self.current_song.stream_url
                head = requests.head(stream, allow_redirects=True, timeout=10)
                if head.status_code == 403:
                    print("Stream URL expired, reloading...")
                    self.current_song = self.getter.reload_stream_url(self.current_song)
                
                
                source = discord.FFmpegPCMAudio(self.current_song.stream_url, **ffmpeg_options)
                
                await self.set_status()
                
            
                self.song_playing_since = time.time()
                self.is_playing_flag = True
                
            
                def after_playing(err):
                    if err:
                        print(f"Player error: {err}")
                    asyncio.run_coroutine_threadsafe(self._play(), self.bot.loop)
                
                self.voice_client.play(source, after=after_playing)
                
            except Exception as e:
                print(f"Error in _play: {e}")
                asyncio.run_coroutine_threadsafe(self._play(), self.bot.loop)


    def get_voice_client_on_reload(self):
        vcs = self.bot.voice_clients
        return vcs[0] if vcs else None

    async def cog_load(self):
        if not self.voice_client and self.get_voice_client_on_reload():
            self.voice_client = self.get_voice_client_on_reload()
            dummy_song = self.getter.db.get_dummy(Song)
            if dummy_song:
                self.current_song = dummy_song


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

            # Get song
            if validators.url(song):
                song_obj = self.getter.get_song_by_url(song)
            else:
                song_obj = self.getter.get_song_by_name(song)

            self.add_to_queue(song_obj)
            song_name = song_obj.name
            
            # Start playing if not already playing
            if not self.is_playing():
                await self._play()
            
            await interaction.followup.send(f"**{song_name}** zur Warteschlange hinzugefügt")
            
        except Exception as e:
            await interaction.followup.send(f"Fehler: {str(e)}")
            
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