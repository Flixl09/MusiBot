import discord
import validators
from discord.ext import commands
from discord import app_commands
from discord.ext.commands import Bot, Cog, check, is_owner, guild_only, Context

from Helpers import Manager

bot = Bot(command_prefix="-", intents=discord.Intents.all(), help_command=None,
          activity=discord.Game(name="Loading..."), status=discord.Status.dnd)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} - {bot.user.id}")
    await bot.add_cog(Manager(bot))
    print("Bot is ready!")
    await bot.change_presence(activity=discord.Game(name="Ready!"), status=discord.Status.online)

@bot.check
async def globally_block_dms(ctx: Context):
    return ctx.guild is not None

@bot.command(name="sync")
@commands.is_owner()
async def sync(ctx: Context):
    await bot.tree.sync()
    await ctx.send("Synced commands!")

with open("token", "r") as f:
    token = f.read().strip()

bot.run(token)