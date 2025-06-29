import logging
import json
import discord
from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, Any, cast
from sqlalchemy.ext.asyncio import AsyncSession


from bot.database.models import WorldState
from bot.database.crud_utils import get_entity_by_attributes # update_entity might not be needed if session.add() is used
from bot.utils.decorators import is_master_role
from sqlalchemy.orm.attributes import flag_modified # For JSONB field updates if necessary

if TYPE_CHECKING:
    from bot.bot_core import RPGBot

logger = logging.getLogger(__name__)

@app_commands.guild_only() # Ensure all commands in this group are guild-only
class WorldStateCmdsCog(commands.Cog, name="Master WorldState"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot
        logger.info("WorldStateCmdsCog initialized.")

    master_ws_group = app_commands.Group(
        name="master_worldstate",
        description="Master commands for managing WorldState custom flags."
        # guild_only=True is inherited from the Cog's decorator
    )

    @master_ws_group.command(name="set_flag", description="Sets or updates a custom world flag.")
    @app_commands.describe(flag_name="The name of the flag (e.g., 'eternal_winter').", flag_value="The value (true, false, number, or text).")
    @is_master_role()
    async def set_flag(self, interaction: Interaction, flag_name: str, flag_value: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        log_prefix = f"set_flag (Guild: {guild_id}, User: {interaction.user.id})"
        logger.info(f"{log_prefix}: Attempting to set flag '{flag_name}' to '{flag_value}'.")

        if not self.bot.game_manager or not self.bot.game_manager.db_service:
            logger.error(f"{log_prefix}: GameManager or DBService not available.")
            await interaction.followup.send("Core game services are unavailable. Please try again later.", ephemeral=True)
            return

        db_service = self.bot.game_manager.db_service
        parsed_value: Any = None

        # Parse flag_value
        if flag_value.lower() == "true":
            parsed_value = True
        elif flag_value.lower() == "false":
            parsed_value = False
        else:
            try:
                parsed_value = int(flag_value)
            except ValueError:
                try:
                    parsed_value = float(flag_value)
                except ValueError:
                    parsed_value = flag_value # Store as string if not bool or number

        session_obj = None # Initialize session_obj to None for broader scope
        try:
            if not self.bot.game_manager or not self.bot.game_manager.db_service:
                logger.error(f"{log_prefix}: GameManager or DBService not available.")
                await interaction.followup.send("Core game services are unavailable. Please try again later.", ephemeral=True)
                return

            db_service = self.bot.game_manager.db_service

            get_session_method = getattr(db_service, "get_session", None)
            if not callable(get_session_method):
                logger.error(f"{log_prefix}: DBService get_session method not available or not callable.")
                await interaction.followup.send("Database service is misconfigured. Cannot set flag.", ephemeral=True)
                return

            async with get_session_method() as session_obj_ctx:
                session = cast(AsyncSession, session_obj_ctx)

                world_state_list = await get_entity_by_attributes(session, WorldState, {"guild_id": guild_id})
                world_state: Optional[WorldState] = world_state_list[0] if world_state_list else None


                if not world_state:
                    logger.info(f"{log_prefix}: No WorldState found, creating one for guild {guild_id}.")
                    # Assuming WorldState model initializes custom_flags to {} by default if not provided
                    world_state = WorldState(guild_id=guild_id, custom_flags={})
                    session.add(world_state)

                # Ensure custom_flags is a dict; it should be by model definition or above creation
                if not isinstance(world_state.custom_flags, dict):
                    logger.warning(f"{log_prefix}: world_state.custom_flags is not a dict for guild {guild_id}. Re-initializing.")
                    world_state.custom_flags = {} # type: ignore[assignment] # Pyright might complain if custom_flags is Column


                # world_state.custom_flags is a Column object, not a dict.
                # We need to modify it in a way that SQLAlchemy understands for JSONB.
                # Create a new dictionary based on the old one, or an empty one.
                current_flags = dict(world_state.custom_flags) if world_state.custom_flags is not None else {}
                current_flags[flag_name.strip()] = parsed_value
                world_state.custom_flags = current_flags # type: ignore[assignment]

                flag_modified(world_state, "custom_flags")
                # session.add(world_state) # Not always necessary if the object is already persistent and tracked

                await session.commit()
                logger.info(f"{log_prefix}: World flag '{flag_name}' successfully set to '{parsed_value}'.")
                await interaction.followup.send(f"World flag '{flag_name}' has been set to `{parsed_value}`.", ephemeral=True)

        except Exception as e:
            logger.error(f"{log_prefix}: Error setting world flag '{flag_name}': {e}", exc_info=True)
            if session_obj and hasattr(session_obj, "rollback") and callable(session_obj.rollback): # type: ignore
                await session_obj.rollback() # type: ignore
            await interaction.followup.send(f"An error occurred while setting the flag: {e}", ephemeral=True)

    @master_ws_group.command(name="remove_flag", description="Removes a custom world flag.")
    @app_commands.describe(flag_name="The name of the flag to remove.")
    @is_master_role()
    async def remove_flag(self, interaction: Interaction, flag_name: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        log_prefix = f"remove_flag (Guild: {guild_id}, User: {interaction.user.id})"
        logger.info(f"{log_prefix}: Attempting to remove flag '{flag_name}'.")

        cleaned_flag_name = flag_name.strip()
        session_obj = None

        try:
            if not self.bot.game_manager or not self.bot.game_manager.db_service:
                logger.error(f"{log_prefix}: GameManager or DBService not available.")
                await interaction.followup.send("Core game services are unavailable. Please try again later.", ephemeral=True)
                return

            db_service = self.bot.game_manager.db_service
            get_session_method = getattr(db_service, "get_session", None)
            if not callable(get_session_method):
                logger.error(f"{log_prefix}: DBService get_session method not available or not callable.")
                await interaction.followup.send("Database service is misconfigured. Cannot remove flag.", ephemeral=True)
                return

            async with get_session_method() as session_obj_ctx:
                session = cast(AsyncSession, session_obj_ctx)
                world_state_list = await get_entity_by_attributes(session, WorldState, {"guild_id": guild_id})
                world_state: Optional[WorldState] = world_state_list[0] if world_state_list else None

                if not world_state or not isinstance(world_state.custom_flags, dict) or cleaned_flag_name not in world_state.custom_flags:
                    logger.warning(f"{log_prefix}: World flag '{cleaned_flag_name}' not found or no flags set, or custom_flags is not a dict.")
                    await interaction.followup.send(f"World flag '{cleaned_flag_name}' not found.", ephemeral=True)
                    return

                # Create a new dictionary from the existing custom_flags
                current_flags = dict(world_state.custom_flags)
                del current_flags[cleaned_flag_name]
                world_state.custom_flags = current_flags # type: ignore[assignment]

                flag_modified(world_state, "custom_flags")
                # session.add(world_state) # Not always necessary

                await session.commit()
                logger.info(f"{log_prefix}: World flag '{cleaned_flag_name}' successfully removed.")
                await interaction.followup.send(f"World flag '{cleaned_flag_name}' has been removed.", ephemeral=True)

        except Exception as e:
            logger.error(f"{log_prefix}: Error removing world flag '{cleaned_flag_name}': {e}", exc_info=True)
            if session_obj and hasattr(session_obj, "rollback") and callable(session_obj.rollback): # type: ignore
                await session_obj.rollback() # type: ignore
            await interaction.followup.send(f"An error occurred while removing the flag: {e}", ephemeral=True)

    @master_ws_group.command(name="view_flags", description="Views all custom world flags.")
    @is_master_role()
    async def view_flags(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        log_prefix = f"view_flags (Guild: {guild_id}, User: {interaction.user.id})"
        logger.info(f"{log_prefix}: User requested to view flags.")

        try:
            if not self.bot.game_manager or not self.bot.game_manager.db_service:
                logger.error(f"{log_prefix}: GameManager or DBService not available.")
                await interaction.followup.send("Core game services are unavailable. Please try again later.", ephemeral=True)
                return

            db_service = self.bot.game_manager.db_service
            get_session_method = getattr(db_service, "get_session", None)
            if not callable(get_session_method):
                logger.error(f"{log_prefix}: DBService get_session method not available or not callable.")
                await interaction.followup.send("Database service is misconfigured. Cannot view flags.", ephemeral=True)
                return

            async with get_session_method() as session_obj_ctx:
                session = cast(AsyncSession, session_obj_ctx)
                world_state_list = await get_entity_by_attributes(session, WorldState, {"guild_id": guild_id})
                world_state: Optional[WorldState] = world_state_list[0] if world_state_list else None


                if not world_state or not isinstance(world_state.custom_flags, dict) or not world_state.custom_flags:
                    logger.info(f"{log_prefix}: No custom world flags are set for this guild or custom_flags is not a dict.")
                    await interaction.followup.send("No custom world flags are currently set.", ephemeral=True)
                    return

                flags_json_str = json.dumps(world_state.custom_flags, indent=2, ensure_ascii=False)
                response_message = f"Current custom world flags:\n```json\n{flags_json_str}\n```"

                if len(response_message) > 2000: # Discord message limit
                    response_message = "Too many flags to display. Please query specific flags or use a database tool."
                    logger.warning(f"{log_prefix}: Serialized flags exceed 2000 characters.")

                logger.info(f"{log_prefix}: Displaying flags: {world_state.custom_flags}")
                await interaction.followup.send(response_message, ephemeral=True)

        except Exception as e:
            logger.error(f"{log_prefix}: Error viewing world flags: {e}", exc_info=True)
            # No rollback needed for a read operation generally
            await interaction.followup.send(f"An error occurred while viewing the flags: {e}", ephemeral=True)

async def setup(bot: "RPGBot"):
    await bot.add_cog(WorldStateCmdsCog(bot))
    logger.info("WorldStateCmdsCog loaded.")
