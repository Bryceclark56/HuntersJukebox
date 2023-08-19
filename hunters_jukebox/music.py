# Suppress noise about console usage from errors
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property
from typing import Any, Optional
import discord
from discord.ext import commands
import youtube_dl


youtube_dl.utils.bug_reports_message = lambda: ''


ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    # bind to ipv4 since ipv6 addresses cause issues sometimes
    'source_address': '0.0.0.0',
}

ffmpeg_options = {
    'options': '-vn',
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume: float = 1.0):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        # TODO: Playlist url support
        if 'entries' in data:
            # Take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

    @classmethod
    async def obtain_data(cls, url, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))

        if 'entries' in data:
            # Take first item from a playlist
            data = data['entries'][0]

        return data


@dataclass
class QueueEntry:
    data: dict[str, Any]

    @cached_property
    def queue_string(self) -> str:
        duration_str = str(self.duration)
        duration_parts = duration_str.split(':')
        if duration_parts[0] == '0':
            duration_str = ':'.join(duration_parts[1:])

        # Try to prevent text wrapping
        title_max_length = 70 - (len(duration_str) + 4)

        title = self.title
        title = (title[:title_max_length] +
                 '...') if len(title) > title_max_length else title

        return f"[{title}]({self.url})  `{duration_str}`"

    @property
    def title(self) -> str:
        return self.data.get('title')

    @cached_property
    def duration(self) -> timedelta:
        duration_string = self.data.get('duration')
        return timedelta(seconds=duration_string)

    @property
    def url(self) -> str:
        return self.data.get('webpage_url')


class Music(commands.Cog):
    bot: commands.Bot
    song_queue: list[QueueEntry]
    current: Optional[QueueEntry]

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.song_queue = []  # Tracks to be played after current
        self.current = None  # Currently playing track

    # Invoke the a command from any context
    def _invoke(self, ctx: commands.Context, cmd_name: str, *args, **kwargs):
        coro = ctx.invoke(
            next(cmd for cmd in self.get_commands() if cmd.name == cmd_name), *args, **kwargs)
        asyncio.run_coroutine_threadsafe(coro, self.bot.loop)

    @commands.command()
    async def next(self, ctx: commands.Context, *, internal_invoke=False):
        """Stops the currently playing song and lays the next song in the queue, if it exists"""

        self.current = None
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()

        if self.song_queue:
            next_song = self.song_queue.pop(0)
            await self._invoke(ctx, 'play', url=next_song.url)
        elif not internal_invoke:
            await ctx.reply("> No more songs to play :(")

    @commands.command()
    async def play(self, ctx: commands.Context, *, url: str):
        """Plays from a url, adding to a queue if player is already active"""

        async with ctx.typing():
            if self.current is None:
                # Immediately play requested URL
                player = await YTDLSource.from_url(url, loop=self.bot.loop)
                self.current = QueueEntry(player.data)
                ctx.voice_client.play(
                    player, after=lambda _: self._invoke(ctx, 'next', internal_invoke=True))
                await ctx.send(embed=discord.Embed(title="Now playing", description=f"[{self.current.title}]({self.current.url})", color=discord.Color.dark_embed(), timestamp=datetime.now()))
            else:
                # Add requested URL to queue
                data = await YTDLSource.obtain_data(url, loop=self.bot.loop)
                entry = QueueEntry(data)
                self.song_queue.append(entry)
                await ctx.send(embed=discord.Embed(title="Added to Queue", description=f"[{entry.title}]({entry.url})", color=discord.Color.dark_green(), timestamp=datetime.now()))

    @commands.command()
    async def queue(self, ctx: commands.Context):
        """Displays the queue of music to be played"""
        # TODO: Support displaying more than the first 10 songs in the queue (use pagination)

        if not self.song_queue:
            await ctx.reply("The queue is empty!")
            return

        async with ctx.typing():
            msg_embed = discord.Embed(
                title=f"Queue",
                color=discord.Color.dark_purple(),
                timestamp=datetime.now()
            )

            for i, entry in enumerate(self.song_queue[:10], start=1):
                msg_embed.add_field(
                    name='',
                    value=f"**{i}.** {entry.queue_string}",
                    inline=False
                )

            await ctx.reply(embed=msg_embed)

    @commands.command()
    async def volume(self, ctx: commands.Context, volume: int):
        """Changes the player's volume"""

        if ctx.voice_client is None:
            return await ctx.reply("> I'm not connected to a voice channel.")

        if volume > 100 or volume < 0:
            # Clamp the desired volume to the range [0, 100]
            volume = max(0, min(volume, 100))

        ctx.voice_client.source.volume = volume / 100
        await ctx.reply(f"> Changed volume to {volume}%")

    @commands.command()
    async def stop(self, ctx: commands.Context):
        """Stops and disconnects the bot from voice"""

        await ctx.voice_client.disconnect()

    @play.before_invoke
    async def ensure_voice(self, ctx: commands.Context):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                await ctx.send("Bruh, you're not in vc; -_-")
                raise commands.CommandError(
                    "Author not connnected to a voice channel.")
