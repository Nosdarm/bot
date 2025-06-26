import discord
from discord.ext import commands
from discord import app_commands
import json
import logging
from typing import Optional

from bot.game.managers.game_manager import GameManager
from bot.database.models.world_related import Location
from sqlalchemy.orm.attributes import flag_modified
from bot.utils.discord_utils import (
    get_discord_user_id_from_interaction,
    is_user_master_or_admin,
    send_error_message,
    send_success_message
)
from bot.utils.i18n_utils import get_localized_string # Replaced LocalizedString, translate_string
from bot.database.guild_transaction import GuildTransaction # For database operations

logger = logging.getLogger(__name__)

class MasterCog(commands.Cog, name="Master Commands"):
    def __init__(self, bot):
        self.bot = bot
        self.game_manager: GameManager = self.bot.get_game_manager()

    async def cog_check(self, ctx_or_interaction) -> bool:
        """Checks if the user is a master or admin before executing any command in this cog."""
        user_id = get_discord_user_id_from_interaction(ctx_or_interaction)
        guild_id_str = str(ctx_or_interaction.guild.id) if ctx_or_interaction.guild else None
        if not guild_id_str:
            # This check should ideally not be needed if commands are guild-only
            # but as a safeguard for direct Cog calls or future non-guild commands.
            if isinstance(ctx_or_interaction, discord.Interaction):
                await send_error_message(ctx_or_interaction, "Master commands must be used within a server (guild).")
            else: # commands.Context
                await ctx_or_interaction.send("Master commands must be used within a server (guild).")
            return False

        is_master = await self.game_manager.is_user_master(guild_id_str, user_id)
        if not is_master:
            # Determine language - assuming interaction.locale for interactions,
            # and guild main language for context commands as a fallback.
            # This might need refinement based on how language management is fully implemented.
            lang = "en" # Default
            if isinstance(ctx_or_interaction, discord.Interaction):
                lang = str(ctx_or_interaction.locale) if ctx_or_interaction.locale else "en"
            elif guild_id_str: # For commands.Context
                # Placeholder: In a real scenario, fetch guild's main language
                # lang = await self.game_manager.get_guild_main_language(guild_id_str) or "en"
                # For now, to avoid adding new async calls in cog_check if not designed for it:
                lang = "en" # Or fetch from a synchronous cache if available

            error_key = "error_not_master_admin" # Key for the translatable string
            # The original LocalizedString seemed to take guild_id_str as an argument,
            # implying it might be used in the string formatting.
            # Let's assume the string is like "You are not a master on server {guild_id}."
            # If so, guild_id would be passed as a kwarg to get_localized_string.
            # For now, assuming the key "error_not_master_admin" doesn't need guild_id for formatting.
            # If it does, it would be: get_localized_string(error_key, lang, guild_id=guild_id_str)

            message_str = get_localized_string(error_key, lang)

            if isinstance(ctx_or_interaction, discord.Interaction):
                await send_error_message(ctx_or_interaction, message_str)
            else: # commands.Context
                await ctx_or_interaction.send(message_str)
            return False
        return True

    @app_commands.command(name="master_add_location_connection", description="Adds a one-way connection between two locations.")
    @app_commands.guild_only()
    @app_commands.describe(
        source_location_id="ID of the source location",
        target_location_id="ID of the target location",
        connection_details_json="JSON string for connection details (e.g., {\"direction_i18n\": {\"en\": \"North\"}, \"travel_time_hours\": 1})"
    )
    async def master_add_location_connection(self, interaction: discord.Interaction,
                                             source_location_id: str,
                                             target_location_id: str,
                                             connection_details_json: str):
        """
        Adds a one-way connection from source_location_id to target_location_id.
        Example connection_details_json:
        {
            "direction_i18n": {"en": "North", "ru": "Север"},
            "path_description_i18n": {"en": "A dusty path leading north.", "ru": "Пыльная тропа, ведущая на север."},
            "travel_time_hours": 1.5,
            "required_items": ["rope", "key_001"],
            "visibility_conditions_json": {"quest_id": "main_quest_01", "step_id": "step_03", "status": "completed"}
        }
        """
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        if source_location_id == target_location_id:
            await send_error_message(interaction, "Source and target location IDs cannot be the same.")
            return

        try:
            connection_details = json.loads(connection_details_json)
            # Basic validation for required fields in connection_details can be added here
            if not isinstance(connection_details.get("direction_i18n"), dict) or \
               not isinstance(connection_details.get("path_description_i18n"), dict):
                await send_error_message(interaction, "connection_details_json must contain 'direction_i18n' and 'path_description_i18n' as objects.")
                return
        except json.JSONDecodeError:
            await send_error_message(interaction, "Invalid JSON format for connection_details_json.")
            return

        try:
            async with GuildTransaction(self.game_manager.db_service.get_session_factory, guild_id) as session:
                source_location = await session.get(Location, source_location_id)
                if not source_location or source_location.guild_id != guild_id:
                    await send_error_message(interaction, f"Source location with ID '{source_location_id}' not found or not in this guild.")
                    return

                target_location = await session.get(Location, target_location_id)
                if not target_location or target_location.guild_id != guild_id:
                    await send_error_message(interaction, f"Target location with ID '{target_location_id}' not found or not in this guild.")
                    return

                if source_location.neighbor_locations_json is None:
                    source_location.neighbor_locations_json = []

                # Check if connection to target already exists to prevent duplicates for the exact same target_id
                # More sophisticated checks could compare all details if multiple paths to same target are allowed but different.
                # For now, assume one explicit connection definition per target_id from source.
                connection_exists = any(conn.get("to_location_id") == target_location_id for conn in source_location.neighbor_locations_json)

                if connection_exists:
                    await send_error_message(interaction, f"Connection from '{source_location_id}' to '{target_location_id}' already exists. Use 'master_modify_location_connection' to change it or 'master_remove_location_connection' to delete it.")
                    return

                new_connection_entry = {
                    "to_location_id": target_location_id,
                    "direction_i18n": connection_details.get("direction_i18n"),
                    "path_description_i18n": connection_details.get("path_description_i18n"),
                    "travel_time_hours": connection_details.get("travel_time_hours"),
                    "required_items": connection_details.get("required_items", []),
                    "visibility_conditions_json": connection_details.get("visibility_conditions_json", {})
                    # any other fields from connection_details can be added here
                }

                source_location.neighbor_locations_json.append(new_connection_entry)
                action_msg = "added new"

                flag_modified(source_location, "neighbor_locations_json")
                await session.commit()
                await send_success_message(interaction, f"Successfully {action_msg} connection from '{source_location_id}' to '{target_location_id}'.")

        except Exception as e:
            logger.error(f"Error in master_add_location_connection for guild {guild_id}: {e}", exc_info=True)
            await send_error_message(interaction, f"An unexpected error occurred: {e}")


    @app_commands.command(name="master_mod_loc_connection", description="Modifies an existing one-way location connection.") # Renamed to fit 32 char limit
    @app_commands.guild_only()
    @app_commands.describe(
        source_location_id="ID of the source location",
        target_location_id="ID of the target location to modify connection to",
        new_connection_details_json="JSON string for new connection details (e.g., {\"direction_i18n\": {\"en\": \"North\"}, \"travel_time_hours\": 1})"
    )
    async def master_mod_loc_connection(self, interaction: discord.Interaction, # Renamed method to match command
                                                source_location_id: str,
                                                target_location_id: str,
                                                new_connection_details_json: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        if source_location_id == target_location_id:
            await send_error_message(interaction, "Source and target location IDs cannot be the same.")
            return

        try:
            new_connection_details = json.loads(new_connection_details_json)
            if not isinstance(new_connection_details.get("direction_i18n"), dict) or \
               not isinstance(new_connection_details.get("path_description_i18n"), dict):
                await send_error_message(interaction, "new_connection_details_json must contain 'direction_i18n' and 'path_description_i18n' as objects.")
                return
        except json.JSONDecodeError:
            await send_error_message(interaction, "Invalid JSON format for new_connection_details_json.")
            return

        try:
            async with GuildTransaction(self.game_manager.db_service.get_session_factory, guild_id) as session:
                source_location = await session.get(Location, source_location_id)
                if not source_location or source_location.guild_id != guild_id:
                    await send_error_message(interaction, f"Source location with ID '{source_location_id}' not found.")
                    return

                if source_location.neighbor_locations_json is None:
                    source_location.neighbor_locations_json = []

                existing_connection_index = -1
                for i, conn in enumerate(source_location.neighbor_locations_json):
                    if conn.get("to_location_id") == target_location_id:
                        existing_connection_index = i
                        break

                if existing_connection_index == -1:
                    await send_error_message(interaction, f"No connection found from '{source_location_id}' to '{target_location_id}' to modify.")
                    return

                # Update the existing connection
                source_location.neighbor_locations_json[existing_connection_index] = {
                    "to_location_id": target_location_id, # Keep target_location_id consistent
                    "direction_i18n": new_connection_details.get("direction_i18n"),
                    "path_description_i18n": new_connection_details.get("path_description_i18n"),
                    "travel_time_hours": new_connection_details.get("travel_time_hours"),
                    "required_items": new_connection_details.get("required_items", []),
                    "visibility_conditions_json": new_connection_details.get("visibility_conditions_json", {})
                }

                flag_modified(source_location, "neighbor_locations_json")
                await session.commit()
                await send_success_message(interaction, f"Successfully modified connection from '{source_location_id}' to '{target_location_id}'.")

        except Exception as e:
            logger.error(f"Error in master_mod_loc_connection for guild {guild_id}: {e}", exc_info=True) # Adjusted logging
            await send_error_message(interaction, f"An unexpected error occurred: {e}")


    @app_commands.command(name="master_del_loc_connection", description="Removes a one-way location connection.") # Renamed to fit 32 char limit master_remove_location_connection -> master_del_loc_connection
    @app_commands.guild_only()
    @app_commands.describe(
        source_location_id="ID of the source location",
        target_location_id="ID of the target location whose connection will be removed"
    )
    async def master_del_loc_connection(self, interaction: discord.Interaction, # Renamed method to match command
                                                source_location_id: str,
                                                target_location_id: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        try:
            async with GuildTransaction(self.game_manager.db_service.get_session_factory, guild_id) as session:
                source_location = await session.get(Location, source_location_id)
                if not source_location or source_location.guild_id != guild_id:
                    await send_error_message(interaction, f"Source location with ID '{source_location_id}' not found.")
                    return

                if source_location.neighbor_locations_json is None:
                    source_location.neighbor_locations_json = []

                original_len = len(source_location.neighbor_locations_json)
                source_location.neighbor_locations_json = [
                    conn for conn in source_location.neighbor_locations_json
                    if conn.get("to_location_id") != target_location_id
                ]

                if len(source_location.neighbor_locations_json) == original_len:
                    await send_error_message(interaction, f"No connection found from '{source_location_id}' to '{target_location_id}' to remove.")
                    return

                flag_modified(source_location, "neighbor_locations_json")
                await session.commit()
                await send_success_message(interaction, f"Successfully removed connection from '{source_location_id}' to '{target_location_id}'.")

        except Exception as e:
            logger.error(f"Error in master_del_loc_connection for guild {guild_id}: {e}", exc_info=True) # Adjusted logging
            await send_error_message(interaction, f"An unexpected error occurred: {e}")


async def setup(bot):
    await bot.add_cog(MasterCog(bot))
    logger.info("MasterCog added to bot.")

# TODO: Implement /master_add_location (basic version)
# TODO: Implement /master_remove_location
# TODO: Implement /master_list_locations
# TODO: Consider a command to add BI-DIRECTIONAL connections easily.
