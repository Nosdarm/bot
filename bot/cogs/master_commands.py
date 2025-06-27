import discord
from discord.ext import commands
from discord import app_commands
import json
import logging
from typing import Optional, List, Dict, Any, Union, TYPE_CHECKING, cast # Added Union, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from bot.bot_core import RPGBot # For type hinting self.bot
    from bot.game.managers.game_manager import GameManager
    from bot.database.models.world_related import Location

from sqlalchemy.orm.attributes import flag_modified # Keep this outside TYPE_CHECKING
from bot.utils.discord_utils import (
    get_discord_user_id_from_interaction,
    is_user_master_or_admin,
    send_error_message,
    send_success_message
)
from bot.utils.i18n_utils import get_localized_string
from bot.database.guild_transaction import GuildTransaction

logger = logging.getLogger(__name__)

class MasterCog(commands.Cog, name="Master Commands"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot
        # Access GameManager via self.bot.game_manager, which should be set up by RPGBot
        # The Optional type hint for self.game_manager handles cases where it might not be immediately available
        # or if there's a loading order issue, though ideally it should always be present after bot setup.
        self.game_manager: Optional["GameManager"] = self.bot.game_manager # type: ignore[assignment]

        if not self.game_manager:
            logger.error("MasterCog: GameManager not found on bot. This cog may not function correctly.")
            # Consider raising an exception or specific handling if GameManager is critical
            # For now, logging an error allows the bot to load other cogs if possible.

    async def cog_check(self, ctx_or_interaction: Union[commands.Context, discord.Interaction]) -> bool:
        """Checks if the user is a master or admin before executing any command in this cog."""
        guild = ctx_or_interaction.guild
        if not guild: # Should not happen with guild_only=True, but defensive
            if isinstance(ctx_or_interaction, discord.Interaction):
                if not ctx_or_interaction.response.is_done(): await ctx_or_interaction.response.send_message("Master commands must be used within a server.", ephemeral=True)
                else: await ctx_or_interaction.followup.send("Master commands must be used within a server.", ephemeral=True)
            else: # commands.Context
                await ctx_or_interaction.send("Master commands must be used within a server.")
            return False

        guild_id_str = str(guild.id)

        if not self.game_manager: # Check again, as it's crucial for is_user_master_or_admin
            msg = "GameManager is not available. Master commands cannot be checked or executed."
            logger.error(msg)
            if isinstance(ctx_or_interaction, discord.Interaction):
                if not ctx_or_interaction.response.is_done(): await ctx_or_interaction.response.send_message(msg, ephemeral=True)
                else: await ctx_or_interaction.followup.send(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
            return False

        # Pass self.game_manager directly
        is_master = await is_user_master_or_admin(ctx_or_interaction, self.game_manager) # is_user_master_or_admin is async

        if not is_master:
            lang = "en" # Default language
            # Determine language for the response
            if isinstance(ctx_or_interaction, discord.Interaction) and ctx_or_interaction.locale:
                lang = str(ctx_or_interaction.locale)
            elif self.game_manager and hasattr(self.game_manager, 'get_rule') and callable(self.game_manager.get_rule):
                lang_result = await self.game_manager.get_rule(guild_id_str, "default_language", "en")
                if lang_result and isinstance(lang_result, str): lang = lang_result

            error_key = "error_not_master_admin"
            # Ensure guild.name is accessed correctly
            guild_name = guild.name if guild else "this server"
            message_str = get_localized_string(
                language=lang,
                string_key=error_key,
                guild_id=guild_id_str, # Pass guild_id as string
                # Ensure params are correctly structured if get_localized_string expects a dict
                params={"guild_name": guild_name} if isinstance(guild_name, str) else {}
            )


            if isinstance(ctx_or_interaction, discord.Interaction):
                if not ctx_or_interaction.response.is_done(): await ctx_or_interaction.response.send_message(message_str, ephemeral=True)
                else: await ctx_or_interaction.followup.send(message_str, ephemeral=True)
            else:
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
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        if not self.game_manager or not self.game_manager.db_service:
            await send_error_message(interaction, "GameManager or DBService not available."); return

        if source_location_id == target_location_id:
            await send_error_message(interaction, "Source and target location IDs cannot be the same."); return
        try:
            connection_details = json.loads(connection_details_json)
            if not isinstance(connection_details.get("direction_i18n"), dict) or \
               not isinstance(connection_details.get("path_description_i18n"), dict):
                await send_error_message(interaction, "connection_details_json must contain 'direction_i18n' and 'path_description_i18n' as objects."); return
        except json.JSONDecodeError:
            await send_error_message(interaction, "Invalid JSON format for connection_details_json."); return

        try:
            if not self.game_manager.db_service: # Should be caught by earlier check, but defensive
                 await send_error_message(interaction, "DBService is not available."); return
            session_factory = self.game_manager.db_service.get_session_factory()
            if not session_factory:
                await send_error_message(interaction, "Session factory not available."); return

            async with GuildTransaction(session_factory, guild_id) as session: # type: ignore[arg-type]
                from bot.database.models.world_related import Location # Import here to avoid circularity if Location is defined elsewhere
                source_location: Optional[Location] = await session.get(Location, source_location_id)
                if not source_location or str(source_location.guild_id) != guild_id:
                    await send_error_message(interaction, f"Source location '{source_location_id}' not found."); return

                target_location: Optional[Location] = await session.get(Location, target_location_id)
                if not target_location or str(target_location.guild_id) != guild_id:
                    await send_error_message(interaction, f"Target location '{target_location_id}' not found."); return

                current_neighbors_any = source_location.neighbor_locations_json
                current_neighbors: List[Dict[str, Any]] = current_neighbors_any if isinstance(current_neighbors_any, list) else []


                if any(isinstance(conn, dict) and conn.get("to_location_id") == target_location_id for conn in current_neighbors):
                    await send_error_message(interaction, f"Connection from '{source_location_id}' to '{target_location_id}' already exists."); return

                new_connection_entry: Dict[str, Any] = { # Explicitly type new_connection_entry
                    "to_location_id": target_location_id,
                    "direction_i18n": connection_details.get("direction_i18n"),
                    "path_description_i18n": connection_details.get("path_description_i18n"),
                    "travel_time_hours": connection_details.get("travel_time_hours"),
                    "required_items": connection_details.get("required_items", []),
                    "visibility_conditions_json": connection_details.get("visibility_conditions_json", {})
                }
                current_neighbors.append(new_connection_entry)
                source_location.neighbor_locations_json = current_neighbors
                flag_modified(source_location, "neighbor_locations_json")
                await session.commit()
                await send_success_message(interaction, f"Successfully added connection from '{source_location_id}' to '{target_location_id}'.")
        except Exception as e:
            logger.error(f"Error in master_add_location_connection for guild {guild_id}: {e}", exc_info=True)
            await send_error_message(interaction, f"An unexpected error occurred: {e}")

    @app_commands.command(name="master_mod_loc_connection", description="Modifies an existing one-way location connection.")
    @app_commands.guild_only()
    @app_commands.describe(
        source_location_id="ID of the source location",
        target_location_id="ID of the target location to modify connection to",
        new_connection_details_json="JSON string for new connection details"
    )
    async def master_mod_loc_connection(self, interaction: discord.Interaction,
                                                source_location_id: str,
                                                target_location_id: str,
                                                new_connection_details_json: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        if not self.game_manager or not self.game_manager.db_service:
            await send_error_message(interaction, "GameManager or DBService not available."); return

        if source_location_id == target_location_id:
            await send_error_message(interaction, "Source and target location IDs cannot be the same."); return
        try:
            new_connection_details = json.loads(new_connection_details_json)
            if not isinstance(new_connection_details.get("direction_i18n"), dict) or \
               not isinstance(new_connection_details.get("path_description_i18n"), dict):
                await send_error_message(interaction, "new_connection_details_json must contain 'direction_i18n' and 'path_description_i18n' as objects."); return
        except json.JSONDecodeError:
            await send_error_message(interaction, "Invalid JSON format for new_connection_details_json."); return

        try:
            if not self.game_manager.db_service: # Defensive check
                 await send_error_message(interaction, "DBService is not available."); return
            session_factory = self.game_manager.db_service.get_session_factory()
            if not session_factory:
                await send_error_message(interaction, "Session factory not available."); return

            async with GuildTransaction(session_factory, guild_id) as session: # type: ignore[arg-type]
                from bot.database.models.world_related import Location # Import here
                source_location: Optional[Location] = await session.get(Location, source_location_id)
                if not source_location or str(source_location.guild_id) != guild_id:
                    await send_error_message(interaction, f"Source location '{source_location_id}' not found."); return

                current_neighbors_any = source_location.neighbor_locations_json
                current_neighbors: List[Dict[str, Any]] = current_neighbors_any if isinstance(current_neighbors_any, list) else []

                existing_connection_index = -1
                for i, conn in enumerate(current_neighbors):
                    if isinstance(conn, dict) and conn.get("to_location_id") == target_location_id:
                        existing_connection_index = i; break
                if existing_connection_index == -1:
                    await send_error_message(interaction, f"No connection found from '{source_location_id}' to '{target_location_id}' to modify."); return

                # Create a new dictionary for the modified connection to ensure proper typing if needed
                modified_connection: Dict[str, Any] = {
                    "to_location_id": target_location_id,
                    # Preserve other potential fields from existing_connection if any, then overwrite/add new ones
                    **(current_neighbors[existing_connection_index] if isinstance(current_neighbors[existing_connection_index], dict) else {}),
                    **new_connection_details
                }
                current_neighbors[existing_connection_index] = modified_connection

                source_location.neighbor_locations_json = current_neighbors
                flag_modified(source_location, "neighbor_locations_json")
                await session.commit()
                await send_success_message(interaction, f"Successfully modified connection from '{source_location_id}' to '{target_location_id}'.")
        except Exception as e:
            logger.error(f"Error in master_mod_loc_connection for guild {guild_id}: {e}", exc_info=True)
            await send_error_message(interaction, f"An unexpected error occurred: {e}")

    @app_commands.command(name="master_del_loc_connection", description="Removes a one-way location connection.")
    @app_commands.guild_only()
    @app_commands.describe(source_location_id="ID of source", target_location_id="ID of target")
    async def master_del_loc_connection(self, interaction: discord.Interaction,
                                                source_location_id: str,
                                                target_location_id: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        if not self.game_manager or not self.game_manager.db_service:
            await send_error_message(interaction, "GameManager or DBService not available."); return

        try:
            if not self.game_manager.db_service: # Defensive check
                 await send_error_message(interaction, "DBService is not available."); return
            session_factory = self.game_manager.db_service.get_session_factory()
            if not session_factory:
                await send_error_message(interaction, "Session factory not available."); return

            async with GuildTransaction(session_factory, guild_id) as session: # type: ignore[arg-type]
                from bot.database.models.world_related import Location # Import here
                source_location: Optional[Location] = await session.get(Location, source_location_id)
                if not source_location or str(source_location.guild_id) != guild_id:
                    await send_error_message(interaction, f"Source location '{source_location_id}' not found."); return

                current_neighbors_any = source_location.neighbor_locations_json
                current_neighbors: List[Dict[str, Any]] = current_neighbors_any if isinstance(current_neighbors_any, list) else []
                original_len = len(current_neighbors)
                new_neighbors = [conn for conn in current_neighbors if not (isinstance(conn, dict) and conn.get("to_location_id") == target_location_id)]

                if len(new_neighbors) == original_len:
                    await send_error_message(interaction, f"No connection from '{source_location_id}' to '{target_location_id}' to remove."); return

                source_location.neighbor_locations_json = new_neighbors
                flag_modified(source_location, "neighbor_locations_json")
                await session.commit()
                await send_success_message(interaction, f"Successfully removed connection from '{source_location_id}' to '{target_location_id}'.")
        except Exception as e:
            logger.error(f"Error in master_del_loc_connection for guild {guild_id}: {e}", exc_info=True)
            await send_error_message(interaction, f"An unexpected error occurred: {e}")

async def setup(bot: "RPGBot"): # Changed type hint to RPGBot
    # The check for GameManagerCog might be an architectural pattern.
    # If GameManager is always expected on RPGBot instance directly, this check might be simplified or removed.
    # For now, keeping the logic but ensuring self.bot.game_manager is the primary source.
    if not bot.game_manager:
         logger.error("MasterCog setup: bot.game_manager not found. MasterCog may not function correctly.")
         # Depending on strictness, could raise commands.ExtensionFailed here
    await bot.add_cog(MasterCog(bot))
    logger.info("MasterCog added to bot.")
