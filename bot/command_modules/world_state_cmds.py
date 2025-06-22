import logging
import json
import discord
from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, Any

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

        async with db_service.get_session() as session:
            try:
                world_state = await get_entity_by_attributes(session, WorldState, {}, guild_id)

                if not world_state:
                    logger.info(f"{log_prefix}: No WorldState found, creating one for guild {guild_id}.")
                    world_state = WorldState(guild_id=guild_id, custom_flags={})
                    session.add(world_state)

                if world_state.custom_flags is None: # Should be initialized by model default, but as a safeguard
                    world_state.custom_flags = {}

                world_state.custom_flags[flag_name.strip()] = parsed_value
                # Mark the JSONB field as modified for SQLAlchemy to detect the change
                flag_modified(world_state, "custom_flags")
                session.add(world_state) # Add to session ensure it's persisted

                await session.commit()
                logger.info(f"{log_prefix}: World flag '{flag_name}' successfully set to '{parsed_value}'.")
                await interaction.followup.send(f"World flag '{flag_name}' has been set to `{parsed_value}`.", ephemeral=True)

            except Exception as e:
                logger.error(f"{log_prefix}: Error setting world flag '{flag_name}': {e}", exc_info=True)
                await session.rollback()
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

        if not self.bot.game_manager or not self.bot.game_manager.db_service:
            logger.error(f"{log_prefix}: GameManager or DBService not available.")
            await interaction.followup.send("Core game services are unavailable. Please try again later.", ephemeral=True)
            return

        db_service = self.bot.game_manager.db_service

        async with db_service.get_session() as session:
            try:
                world_state = await get_entity_by_attributes(session, WorldState, {}, guild_id)

                if not world_state or world_state.custom_flags is None or cleaned_flag_name not in world_state.custom_flags:
                    logger.warning(f"{log_prefix}: World flag '{cleaned_flag_name}' not found or no flags set.")
                    await interaction.followup.send(f"World flag '{cleaned_flag_name}' not found.", ephemeral=True)
                    return

                del world_state.custom_flags[cleaned_flag_name]
                flag_modified(world_state, "custom_flags")
                session.add(world_state)

                await session.commit()
                logger.info(f"{log_prefix}: World flag '{cleaned_flag_name}' successfully removed.")
                await interaction.followup.send(f"World flag '{cleaned_flag_name}' has been removed.", ephemeral=True)

            except Exception as e:
                logger.error(f"{log_prefix}: Error removing world flag '{cleaned_flag_name}': {e}", exc_info=True)
                await session.rollback()
                await interaction.followup.send(f"An error occurred while removing the flag: {e}", ephemeral=True)

    @master_ws_group.command(name="view_flags", description="Views all custom world flags.")
    @is_master_role()
    async def view_flags(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        log_prefix = f"view_flags (Guild: {guild_id}, User: {interaction.user.id})"
        logger.info(f"{log_prefix}: User requested to view flags.")

        if not self.bot.game_manager or not self.bot.game_manager.db_service:
            logger.error(f"{log_prefix}: GameManager or DBService not available.")
            await interaction.followup.send("Core game services are unavailable. Please try again later.", ephemeral=True)
            return

        db_service = self.bot.game_manager.db_service

        async with db_service.get_session() as session:
            try:
                world_state = await get_entity_by_attributes(session, WorldState, {}, guild_id)

                if not world_state or not world_state.custom_flags:
                    logger.info(f"{log_prefix}: No custom world flags are set for this guild.")
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
