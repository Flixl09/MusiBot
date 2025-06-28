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
    try:
        # Guild-specific sync
        guild = discord.Object(id=915698061530001448)
        bot.tree.copy_global_to(guild=guild)
        synced_guild = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced_guild)} commands to guild")
        
        await ctx.send(f"Synced {len(synced_guild)} to guild!")
    except Exception as e:
        print(f"Sync error: {e}")
        await ctx.send(f"Sync failed: {e}")

@bot.command(name="suicide")
@commands.is_owner()
async def suicide(ctx: Context):
    try:
        await bot.remove_cog("Manager")
        await bot.add_cog(Manager(bot))
        # Re-sync after reloading
        guild = discord.Object(id=915698061530001448)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        await ctx.send("MUSIIIIII REEEELOADDDDEEEEEEEDDDD DAN DAN DANDAN DANDAN DANDANDANDAN DAN DAN")
    except Exception as e:
        await ctx.send(f"Reload failed: {e}")
        
with open("token", "r") as f:
    token = f.read().strip()

bot.run(token)