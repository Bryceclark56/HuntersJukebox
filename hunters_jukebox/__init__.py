import asyncio
import os

import discord
from discord.ext import commands
from aiohttp import ClientSession
from dotenv import load_dotenv

from hunters_jukebox.music import Music


class HuntersJukebox(commands.Bot):
    def __init__(
        self,
        *args,
        initial_extensions: list[str],
        web_client: ClientSession,
        testing_guild_id: int | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.initial_extensions = initial_extensions
        self.web_client = web_client
        self.testing_guild_id = testing_guild_id

    async def setup_hook(self) -> None:
        for extension in self.initial_extensions:
            await self.load_extension(extension)

        if self.testing_guild_id is not None:
            guild = discord.Object(self.testing_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)


async def add_cogs(bot: commands.Bot):
    cogs = [
        Music,
    ]

    for cog in cogs:
        await bot.add_cog(cog(bot))


async def main():
    async with ClientSession() as our_client:
        exts = []
        intents = discord.Intents.default()
        async with HuntersJukebox(commands.when_mentioned_or('h!'), web_client=our_client, initial_extensions=exts, intents=intents) as bot:
            await add_cogs(bot)

            bot_token = os.getenv('BOT_TOKEN')
            if bot_token is None:
                print("Bot token not found; is BOT_TOKEN defined in this environment?")
                return

            await bot.start(bot_token)

if __name__ == '__main__':
    load_dotenv()
    asyncio.run(main())
