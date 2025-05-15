import discord
from discord import slash_command # Use these decorators if command file is added as extension (Cog)
from typing import Optional

# --- Temporary global references ---
from bot.bot_core import global_game_manager, get_bot_instance, _send_message_from_manager
# --- End temporary global references ---

TEST_GUILD_IDS = [] # Add your test server ID(s)


@slash_command(name="look", description="Оглядеться вокруг в текущей локации.", guild_ids=TEST_GUILD_IDS)
async def cmd_look(ctx: discord.ApplicationContext):
    await ctx.defer()
    if global_game_manager:
        response_data = await global_game_manager.process_player_action(
            server_id=ctx.guild.id,
            discord_user_id=ctx.author.id,
            action_type="look",
            action_data={}
            # Need to pass ctx.channel here eventually if response needs to go there specifically
        )
        await ctx.followup.send(response_data.get("message", "**Ошибка:** Неизвестный ответ от мастера."))
    else:
        await ctx.followup.send("**Ошибка Мастера:** Игровая система недоступна.")


@slash_command(name="move", description="Переместиться в другую локацию.", guild_ids=TEST_GUILD_IDS)
async def cmd_move(ctx: discord.ApplicationContext, destination: str):
    await ctx.defer()
    if global_game_manager:
        # Temporarily check if the command is used in a mapped location channel, ignore if not?
        # Or process anyway? Let's process if game started.
        response_data = await global_game_manager.process_player_action(
            server_id=ctx.guild.id,
            discord_user_id=ctx.author.id,
            action_type="move",
            action_data={"destination": destination}
        )
        await ctx.followup.send(response_data.get("message", "**Ошибка:** Неизвестный ответ от мастера."))
    else:
        await ctx.followup.send("**Ошибка Мастера:** Игровая система недоступна.")

# Add other exploration related commands here
# @slash_command(...)
# async def cmd_examine(...)
# bot/command_modules/exploration_cmds.py
import discord
from discord import slash_command # Or commands.Cog
from typing import Optional

# --- Temporary global references ---
from bot.bot_core import global_game_manager # Assuming bot_core exposes this globally
# --- End temporary global references ---

TEST_GUILD_IDS = [] # Add your test server ID(s)


@slash_command(name="look", description="Оглядеться вокруг в текущей локации.", guild_ids=TEST_GUILD_IDS)
async def cmd_look(ctx: discord.ApplicationContext):
    await ctx.defer()
    if global_game_manager:
        response_data = await global_game_manager.process_player_action(
            server_id=ctx.guild.id,
            discord_user_id=ctx.author.id,
            action_type="look",
            action_data={}
        )
        await ctx.followup.send(response_data.get("message", "Произошла ошибка."))
    else:
        await ctx.followup.send("**Ошибка Мастера:** Игровая система недоступна.")


@slash_command(name="move", description="Переместиться в другую локацию.", guild_ids=TEST_GUILD_IDS)
async def cmd_move(ctx: discord.ApplicationContext, destination: str):
    await ctx.defer()
    if global_game_manager:
        response_data = await global_game_manager.process_player_action(
            server_id=ctx.guild.id,
            discord_user_id=ctx.author.id,
            action_type="move",
            action_data={"destination": destination}
        )
        await ctx.followup.send(response_data.get("message", "Произошла ошибка."))
    else:
        await ctx.followup.send("**Ошибка Мастера:** Игровая система недоступна.")

# --- New Command: Skill Check ---
# Example: /check skill_name:stealth complexity:hard target_description:"пройти мимо стражника"
@slash_command(name="check", description="Выполнить проверку навыка.", guild_ids=TEST_GUILD_IDS)
async def cmd_check(ctx: discord.ApplicationContext, skill_name: str, complexity: str = "medium", target_description: Optional[str] = None):
     await ctx.defer()
     if global_game_manager:
         response_data = await global_game_manager.process_player_action(
             server_id=ctx.guild.id,
             discord_user_id=ctx.author.id,
             action_type="skill_check", # Define this as the action type
             action_data={"skill_name": skill_name, "complexity": complexity, "target_description": target_description or f"совершить действие, требующее навыка {skill_name}"} # Pass relevant data
             # Can add environmental_modifiers based on location, status_modifiers based on char status here
             # Modifiers can be retrieved by process_player_action or passed in action_data
         )
         await ctx.followup.send(response_data.get("message", "Произошла ошибка при выполнении проверки."))
     else:
        await ctx.followup.send("**Ошибка Мастера:** Игровая система недоступна.")

@slash_command(name="look", description="Оглядеться вокруг в текущей локации.", guild_ids=TEST_GUILD_IDS)
async def cmd_look(ctx: discord.ApplicationContext):
    await ctx.defer()
    if global_game_manager:
        response_data = await global_game_manager.process_player_action(
            server_id=ctx.guild.id,
            discord_user_id=ctx.author.id,
            action_type="look",
            action_data={},
            ctx_channel_id=ctx.channel.id # Pass context channel ID
        )
        # Use the target_channel_id from the response
        target_channel = get_bot_instance().get_channel(response_data.get("target_channel_id", ctx.channel.id)) if get_bot_instance() else None
        if target_channel:
             # await ctx.followup.send(response_data.get("message", "Произошла ошибка.")) # Old: sends to command channel
             await target_channel.send(response_data.get("message", "**Мастер:** Произошла ошибка при описании локации.")) # New: send to destination/output channel

        else:
            await ctx.followup.send(response_data.get("message", "**Мастер:** Произошла ошибка при описании локации. Не удалось найти целевой канал.") if "Ошибка" in response_data.get("message", "") else "**Мастер:** Произошла ошибка при описании локации.")

    else:
        await ctx.followup.send("**Ошибка Мастера:** Игровая система недоступна.")


@slash_command(name="move", description="Переместиться в другую локацию.", guild_ids=TEST_GUILD_IDS)
async def cmd_move(ctx: discord.ApplicationContext, destination: str):
    await ctx.defer()
    if global_game_manager:
        response_data = await global_game_manager.process_player_action(
            server_id=ctx.guild.id,
            discord_user_id=ctx.author.id,
            action_type="move",
            action_data={"destination": destination},
            ctx_channel_id=ctx.channel.id # Pass context channel ID
        )
        # ActionProcessor returns where to send the message
        target_channel = get_bot_instance().get_channel(response_data.get("target_channel_id", ctx.channel.id)) if get_bot_instance() else None
        if target_channel:
             # Send the main response to the target channel (destination)
             # await ctx.followup.send("Перемещаетесь...") # Optional placeholder while thinking
             await target_channel.send(response_data.get("message", "**Мастер:** Произошла ошибка при перемещении."))

        else:
             # If destination channel is invalid, send error back to context channel
             await ctx.followup.send(response_data.get("message", "**Мастер:** Произошла ошибка при перемещении. Не удалось найти целевой канал.") if "Ошибка" in response_data.get("message", "") else "**Мастер:** Произошла ошибка при перемещении.")

    else:
        await ctx.followup.send("**Ошибка Мастера:** Игровая система недоступна.")

# Update /check as well to use target_channel_id
@slash_command(name="check", description="Выполнить проверку навыка.", guild_ids=TEST_GUILD_IDS)
async def cmd_check(ctx: discord.ApplicationContext, skill_name: str, complexity: str = "medium", target_description: Optional[str] = None):
     await ctx.defer()
     if global_game_manager:
         response_data = await global_game_manager.process_player_action(
             server_id=ctx.guild.id,
             discord_user_id=ctx.author.id,
             action_type="skill_check",
             action_data={"skill_name": skill_name, "complexity": complexity, "target_description": target_description or f"совершить действие, требующее навыка {skill_name}"},
             ctx_channel_id=ctx.channel.id # Pass context channel ID
         )
         # Use the target_channel_id from the response
         target_channel = get_bot_instance().get_channel(response_data.get("target_channel_id", ctx.channel.id)) if get_bot_instance() else None
         if target_channel:
             await target_channel.send(response_data.get("message", "Произошла ошибка при выполнении проверки."))
         else:
             await ctx.followup.send(response_data.get("message", "Произошла ошибка при выполнении проверки. Не удалось найти целевой канал.") if "Ошибка" in response_data.get("message", "") else "Произошла ошибка при выполнении проверки.")

     else:
        await ctx.followup.send("**Ошибка Мастера:** Игровая система недоступна.")