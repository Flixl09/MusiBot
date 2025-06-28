import discord
import validators
from discord.ext import commands
from discord import app_commands
from discord.ext.commands import Bot, Cog, check, is_owner, guild_only, Context

from Helpers import Manager

bot = Bot(command_prefix="-", intents=discord.Intents.all(), help_command=None,owner_id=707656939869306973,
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

@bot.command(name="suicide")
@commands.is_owner()
async def suicide(ctx: Context):
    await bot.remove_cog("Manager")
    await bot.add_cog(Manager(bot))
    await ctx.send("MUSIIIIII REEEELOADDDDEEEEEEEDDDD DAN DAN DANDAN DANDAN DANDANDANDAN DAN DAN")

with open("token", "r") as f:
    token = f.read().strip()

bot.run(token)