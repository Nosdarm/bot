import discord
from discord.ext import commands
from typing import Union, Optional # Added Optional

# Placeholder for discord utility functions - REMOVED
# def placeholder_function():
#    pass

def get_discord_user_id_from_interaction(ctx_or_interaction: Union[discord.Interaction, commands.Context]) -> Optional[int]:
    """
    Retrieves the Discord user ID from an Interaction or Context object.
    Returns None if the user ID cannot be determined (e.g., unexpected type).
    """
    if isinstance(ctx_or_interaction, discord.Interaction):
        return ctx_or_interaction.user.id
    elif isinstance(ctx_or_interaction, commands.Context):
        return ctx_or_interaction.author.id
    return None


# Basic stubs for other functions that were imported in master_commands.py
# These will need proper implementation later.
async def send_error_message(interaction_or_ctx, message_content: str, ephemeral: bool = True):
    print(f"STUB: Sending error message: {message_content}")
    if isinstance(interaction_or_ctx, discord.Interaction):
        if not interaction_or_ctx.response.is_done():
            await interaction_or_ctx.response.send_message(f"ERROR: {message_content}", ephemeral=ephemeral)
        else:
            await interaction_or_ctx.followup.send(f"ERROR: {message_content}", ephemeral=ephemeral)
    elif isinstance(interaction_or_ctx, commands.Context):
        await interaction_or_ctx.send(f"ERROR: {message_content}")

async def send_success_message(interaction_or_ctx, message_content: str, ephemeral: bool = True):
    print(f"STUB: Sending success message: {message_content}")
    if isinstance(interaction_or_ctx, discord.Interaction):
        if not interaction_or_ctx.response.is_done():
            await interaction_or_ctx.response.send_message(f"SUCCESS: {message_content}", ephemeral=ephemeral)
        else:
            await interaction_or_ctx.followup.send(f"SUCCESS: {message_content}", ephemeral=ephemeral)
    elif isinstance(interaction_or_ctx, commands.Context):
        await interaction_or_ctx.send(f"SUCCESS: {message_content}")

async def is_user_master_or_admin(interaction_or_ctx, game_manager, guild_id: str, user_id: int) -> bool:
    # This is a simplified stub. The actual logic might be more complex
    # and involve checking roles or specific user IDs stored in game_manager or DB.
    print(f"STUB: Checking if user {user_id} in guild {guild_id} is master/admin.")
    # Example: based on discord permissions (admin) or a game_manager check (master)
    if isinstance(interaction_or_ctx, discord.Interaction):
        if interaction_or_ctx.user.guild_permissions.administrator: # type: ignore
            return True
    elif isinstance(interaction_or_ctx, commands.Context):
        if interaction_or_ctx.author.guild_permissions.administrator: # type: ignore
            return True
    # Fallback to game_manager check (assuming it exists and works this way)
    # if game_manager and hasattr(game_manager, 'is_user_master'):
    #     return await game_manager.is_user_master(guild_id, user_id)
    return False # Default to False for the stub
