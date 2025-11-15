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
    "extractor_args": {
        "youtube": {
            "player_client": ["default", "-tv_simply"]
        }
    }
}

ffmpeg_before_options = (
    "-reconnect 1 " 
    "-reconnect_streamed 1 "
    "-reconnect_at_eof 0 " 
    "-reconnect_delay_max 2 "
)
ffmpeg_options = {
    'options': '-vn',
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
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info("ytsearch:"+name, download=False)["entries"][0]
            artist = self.db.get_or_add_by_name(Artist, info['channel'])
            song = Song(name=info['title'], url=info['webpage_url'], duration=info['duration'], artists=artist, stream_url=info['url'], platforms=self.yt)
            self.db.add(Song, song)
            return song

    def fetch_from_sc(self, name: str) -> Song:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info("scsearch:"+name, download=False)["entries"][0]
            artist = self.db.get_or_add_by_name(Artist, info['artist'])
            song = Song(name=info['title'], url=info['webpage_url'], duration=info['duration'], artists=artist, stream_url=info['url'], platforms=self.sc)
            self.db.add(Song, song)
            return song

    def fetch_from_url(self, url: str) -> Song:
        if "?v=" in url:
            urlpart = parse_qs(urlparse(url).query).get('v', [None])[0]
        else:
            urlpart = url.split("/")[-1]

        url = "https://www.youtube.com/watch?v=" + urlpart
        print("URL: ", url)
        if self.db.get_by_url(Song, url):
            return self.db.get_by_url(Song, url)

        with YoutubeDL(ydl_opts) as ydl:
            artist = None
            platform = None
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise InvalidURL("Invalid URL")

            if self.validate_yt_url(url):
                artist = self.db.get_or_add_by_name(Artist, info['channel'])
                if artist is None:
                    artist = Artist(name=info['channel'])
                    self.db.add(Artist, artist)
                platform = self.yt
            elif self.validate_sc_url(url):
                artist = self.db.get_or_add_by_name(Artist, info['artist'])
                if artist is None:
                    artist = Artist(name=info['artist'])
                    self.db.add(Artist, artist)
                platform = self.sc
            song = Song(name=info['title'], url=info['webpage_url'], duration=info['duration'], artists=artist, stream_url=info['url'], platforms=platform)
            self.db.add(Song, song)
            return song

    def get_song_by_name(self, name: str) -> Song:
        db_song = self.db.get_by_name(Song, name)
        if db_song:
            return db_song
        else:
            return self.fetch_from_yt(name)


    def get_songs_by_name(self, names: List[str]) -> List[Song]:
        songs: List[Song] = []
        for name in names:
            db_song = self.db.get_by_name(Song, name)
            if db_song:
                songs.append(db_song)
            else:
                song = self.fetch_from_yt(name)
                songs.append(song)
        return songs

    def get_song_by_url(self, url: str) -> Song:
        db_song = self.db.get_by_url(Song, url)
        if db_song:
            return db_song
        else:
            return self.fetch_from_url(url)

    def reload_stream_url(self, song: Song) -> Song:
        s: Song = song
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(song.url, download=False)
            s.stream_url = info['url']
            self.db.update(Song, s)
        return s

    def get_stream_url_with_time(self, song: Song, time: int) -> Song:
        s: Song = song
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(song.url, download=False)
            s.stream_url = info['url'] + "?p=" + str(floor(time))
        return s



class Manager(Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.queue: List[Song] = []
        self.current_song: Song = None
        self.voice_client: VoiceClient = None
        self.getter: Getter = Getter()
        self.tree = bot.tree
        self.song_playing_since: Optional[float] = None

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
        if self.voice_client and self.voice_client.channel and self.voice_client.source and self.current_song:
            return True
        return False

    def get_voice_client(self) -> VoiceClient:
        return self.voice_client

    def is_connected(self) -> bool:
        return self.voice_client.is_connected()

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
            self.voice_client: VoiceClient = await channel.connect()
            self.voice_client.wait_until_connected()
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
        if self.current_song:
            await self.bot.change_presence(activity=discord.Game(name=self.current_song.name))
        else:
            await self.bot.change_presence(activity=discord.Game(name="Nix"))

    def run_play(self, source):
        self.song_playing_since = time.time()
        self.voice_client.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(self._play), bitrate=256, signal_type="music")

    def _play(self, error=None):
        self.song_playing_since = None
        if error:
            print(f"Error playing song: {error}")

        self.next()
        if self.current_song is None:
            return

        print("Playing1:", self.current_song)
        stream = self.current_song.stream_url
        head = requests.head(stream, allow_redirects=True)
        if head.status_code == 403:
            self.current_song = self.getter.reload_stream_url(self.current_song)
            print("Reloaded URL")
        source = discord.FFmpegPCMAudio(self.current_song.stream_url, **ffmpeg_options)
        self.bot.loop.create_task(self.set_status())
        threading.Thread(target=self.run_play, args=(source, )).start()


    def get_voice_client_on_reload(self):
        vcs = self.bot.voice_clients
        return vcs[0] if vcs else None

    async def cog_load(self):
        if not self.voice_client and self.get_voice_client_on_reload():
            self.voice_client = self.get_voice_client_on_reload()
            self.current_song = self.getter.db.get_dummy(Song)


    @Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if self.voice_client and self.voice_client.channel:
            if len(self.voice_client.channel.members) == 1:
                await self._disconnect()
                await self.set_status()
        if member == self.bot.user:
            if not after.channel:
                self.voice_client = None
                self.current_song = None
                self.queue.clear()
                await self.set_status()

    @app_commands.command(name="play", description="Play a song")
    @app_commands.describe(song="Name or URL of the song")
    async def play(self, interaction: discord.Interaction, *, song: str):
        await interaction.response.defer()

        if not interaction.user.voice:
            raise UserNotInVoiceException()
        if not self.voice_client:
            await self.connect_to_channel(interaction.user.voice.channel)
        if not interaction.user.voice.channel == self.voice_client.channel:
            raise DifferentVoiceChannelException()

        if validators.url(song):
            song: Song = self.getter.fetch_from_url(song)
        else:
            song: Song = self.getter.get_song_by_name(song)

        self.add_to_queue(song)
        song_name = song.name
        if not self.is_playing():
            self._play()
        await interaction.followup.send(f"{song_name} zur Warteschlange hinzugefügt")


    @app_commands.command(name="skip", description="Skip the current song")
    async def skip(self, interaction: discord.Interaction):
        if not self.voice_client:
            raise BotNotInVoiceException()
        if not interaction.user.voice.channel == self.voice_client.channel:
            raise DifferentVoiceChannelException()

        if self.is_playing():
            self.voice_client.stop()
            await interaction.response.send_message(f"Song geskippt")
            self._play()
        else:
            await interaction.response.send_message("Ich spiele nichts")

    @app_commands.command(name="stop", description="Stop the current song")
    async def stop(self, interaction: discord.Interaction):
        if not self.voice_client:
            raise BotNotInVoiceException()
        if not interaction.user.voice.channel == self.voice_client.channel:
            raise DifferentVoiceChannelException()

        if self.is_playing():
            await interaction.response.send_message(f"Halt Stopp")
            self.current_song = None
            self.queue.clear()
            self.voice_client.stop()
        else:
            await interaction.response.send_message("Ich spiele nichts")

    @app_commands.command(name="queue", description="Show the current queue")
    @app_commands.describe(page="Page number of the queue")
    async def queue(self, interaction: discord.Interaction, page: int = 1):
        if not self.voice_client:
            raise BotNotInVoiceException()
        if not interaction.user.voice.channel == self.voice_client.channel:
            raise DifferentVoiceChannelException()
        page = 1 if page < 1 else page
        start = (page - 1) * 15
        end = start + 15
        queue = ''
        for i, song in enumerate(self.queue[start:end], start=start):
            queue += '`{0}.` [**{1.name}**]({1.url})\n'.format(i + 1, song)
        embed = Embed(colour=0x00FF00,
                      description=f'**{len(self.get_queue())} tracks**\nDuration: {timedelta(seconds=self.duration())}\n\n{queue}')
        embed.set_footer(text=f'Viewing page {page} of {len(self.queue) // 15 + 1}')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="disconnect", description="Verlasse den Voice Channel")
    async def disconnect(self, interaction: discord.Interaction):
        if not self.voice_client:
            raise BotNotInVoiceException()
        if not interaction.user.voice.channel == self.voice_client.channel:
            raise DifferentVoiceChannelException()

        await self._disconnect()

    @app_commands.command(name="clear", description="Zeige die Warteschlange")
    async def clear(self, interaction: discord.Interaction):
        if not self.voice_client:
            raise BotNotInVoiceException()
        if not interaction.user.voice.channel == self.voice_client.channel:
            raise DifferentVoiceChannelException()

        self.clear_queue()
        await interaction.response.send_message("Warteschlange gelöscht")

    @app_commands.command(name="now", description="Zeige den aktuellen Song")
    async def now(self, interaction: discord.Interaction):
        if not self.voice_client:
            raise BotNotInVoiceException()
        if not interaction.user.voice.channel == self.voice_client.channel:
            raise DifferentVoiceChannelException()

        if self.is_playing():
            await interaction.response.send_message(f"Es wird gespielt: {self.current_song.name}:{self.current_song.duration}\n{self.current_song.url}")
        else:
            await interaction.response.send_message("Ich spiele nichts")

    @app_commands.command(name="shuffle", description="Mische die Warteschlange")
    async def shuffle(self, interaction: discord.Interaction):
        if not self.voice_client:
            raise BotNotInVoiceException()
        if not interaction.user.voice.channel == self.voice_client.channel:
            raise DifferentVoiceChannelException()

        random.shuffle(self.queue)
        await interaction.response.send_message("Warteschlange gemischt")

    @app_commands.command(name="leave", description="Lasse den Bot den Channel verlassen wenn niemand mehr da ist")
    async def leave(self, interaction: discord.Interaction):
        if not self.voice_client:
            raise BotNotInVoiceException()
        if not interaction.user.voice.channel == self.voice_client.channel:
            raise DifferentVoiceChannelException()

        await self._disconnect()
        await self.queue.clear()
        self.current_song = None
        await interaction.response.send_message("Ich habe den Channel verlassen")

    @app_commands.command(name="playnext", description="Spiele den Song als nächstes")
    @app_commands.describe(song="Name or URL of the song")
    async def playnext(self, interaction: discord.Interaction, *, song: str):
        await interaction.response.defer()
        if not interaction.user.voice:
            raise UserNotInVoiceException()
        if not self.voice_client:
            await self.connect_to_channel(interaction.user.voice.channel)
        if not interaction.user.voice.channel == self.voice_client.channel:
            raise DifferentVoiceChannelException()

        if validators.url(song):
            song: Song = self.getter.fetch_from_url(song)
        else:
            song: Song = self.getter.get_song_by_name(song)

        self.queue.insert(0, song)
        song_name = song.name
        if not self.is_playing():
            self._play()
        await interaction.followup.send(f"{song_name} wird als nächstes gespielt")
