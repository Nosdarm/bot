from __future__ import annotations
import logging
import json
from typing import Optional, TYPE_CHECKING

import discord
from discord import app_commands, Interaction
from discord.ext import commands

from bot.models.pending_generation import PendingStatus, GenerationType # Enums
# Assuming PendingGenerationCRUD can be accessed via GameManager or DBService directly if needed
# from bot.persistence.pending_generation_crud import PendingGenerationCRUD
from bot.utils.decorators import is_master_or_admin # Assuming this decorator exists and works

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    from bot.ai.generation_manager import AIGenerationManager
    from bot.persistence.pending_generation_crud import PendingGenerationCRUD


logger = logging.getLogger(__name__)

class ModerationCog(commands.Cog, name="Moderation Commands"):
    def __init__(self, bot: RPGBot):
        self.bot = bot

    def _get_game_manager(self) -> Optional[GameManager]:
        if hasattr(self.bot, 'game_manager') and self.bot.game_manager:
            return self.bot.game_manager
        logger.error("ModerationCog: GameManager not found on bot instance.")
        return None

    def _get_ai_generation_manager(self) -> Optional[AIGenerationManager]:
        game_mngr = self._get_game_manager()
        if game_mngr and hasattr(game_mngr, 'ai_generation_manager') and game_mngr.ai_generation_manager:
            return game_mngr.ai_generation_manager
        logger.error("ModerationCog: AIGenerationManager not found on GameManager.")
        return None

    def _get_pending_gen_crud(self) -> Optional[PendingGenerationCRUD]:
        # PendingGenerationCRUD is often initialized within AIGenerationManager or accessible via DBService
        # For this example, let's assume AIGenerationManager holds it, or we get it from DBService
        ai_gen_mngr = self._get_ai_generation_manager()
        if ai_gen_mngr and hasattr(ai_gen_mngr, 'pending_generation_crud'):
            return ai_gen_mngr.pending_generation_crud

        # Fallback or alternative: get from DBService if structured that way
        game_mngr = self._get_game_manager()
        if game_mngr and game_mngr.db_service:
             # This assumes PendingGenerationCRUD might be directly on db_service or needs instantiation
             # For consistency with AIGenManager, using its instance is preferred.
             # This path is a placeholder if direct access is needed.
            from bot.persistence.pending_generation_crud import PendingGenerationCRUD as CrudStandalone
            return CrudStandalone(game_mngr.db_service)

        logger.error("ModerationCog: PendingGenerationCRUD could not be accessed.")
        return None

    @app_commands.command(name="master_review_generation", description="Review AI-generated content awaiting moderation.")
    @app_commands.describe(pending_id="The ID of the pending generation to review.")
    @is_master_or_admin() # Apply permission check
    @app_commands.guild_only()
    async def review_generation(self, interaction: Interaction, pending_id: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        crud = self._get_pending_gen_crud()
        if not crud:
            await interaction.followup.send("Error: Moderation tools are not properly configured (CRUD access).", ephemeral=True)
            return

        game_mngr = self._get_game_manager()
        if not game_mngr or not game_mngr.db_service:
            await interaction.followup.send("Error: Database service not available.", ephemeral=True)
            return

        try:
            async with game_mngr.db_service.get_session() as session: # Use DBService for session
                record = await crud.get_pending_generation_by_id(session, pending_id, guild_id)

            if not record:
                await interaction.followup.send(f"No pending generation found with ID `{pending_id}` for this guild.", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"Review AI Generation: {record.request_type.value} (ID: {record.id})",
                description=f"Status: **{record.status.value}**\nRequested by: <@{record.created_by_user_id}> on {record.created_at.strftime('%Y-%m-%d %H:%M:%S UTC') if record.created_at else 'N/A'}",
                color=discord.Color.blue()
            )
            if record.request_params_json:
                 embed.add_field(name="Request Parameters", value=f"```json\n{json.dumps(record.request_params_json, indent=2, ensure_ascii=False)}\n```", inline=False)
            if record.parsed_data_json:
                # Display snippet of parsed data
                parsed_data_str = json.dumps(record.parsed_data_json, indent=2, ensure_ascii=False)
                max_len = 1000
                snippet = parsed_data_str[:max_len] + "..." if len(parsed_data_str) > max_len else parsed_data_str
                embed.add_field(name="Parsed Data (Snippet)", value=f"```json\n{snippet}\n```", inline=False)
            else:
                embed.add_field(name="Parsed Data", value="No parsed data available or not JSON.", inline=False)
                if record.raw_ai_output_text: # Show raw if parsed is missing
                    snippet = record.raw_ai_output_text[:max_len] + "..." if len(record.raw_ai_output_text) > max_len else record.raw_ai_output_text
                    embed.add_field(name="Raw AI Output (Snippet)", value=f"```\n{snippet}\n```", inline=False)


            if record.validation_issues_json:
                issues_str = "\n".join([f"- `loc`: {issue.get('loc')}, `type`: {issue.get('type')}, `msg`: {issue.get('msg')}" for issue in record.validation_issues_json][:5]) # Show first 5
                embed.add_field(name=f"Validation Issues ({len(record.validation_issues_json)} total)", value=issues_str if issues_str else "None", inline=False)

            if record.status == PendingStatus.PENDING_MODERATION:
                embed.set_footer(text=f"Use /master_approve_generation id:{record.id} or /master_reject_generation id:{record.id}")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in /master_review_generation for ID {pending_id}: {e}", exc_info=True)
            await interaction.followup.send("An unexpected error occurred while reviewing the generation.", ephemeral=True)


    @app_commands.command(name="master_approve_generation", description="Approves AI-generated content and attempts to apply it.")
    @app_commands.describe(pending_id="The ID of the pending generation to approve.")
    @is_master_or_admin()
    @app_commands.guild_only()
    async def approve_generation(self, interaction: Interaction, pending_id: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        moderator_user_id = str(interaction.user.id)

        ai_gen_mngr = self._get_ai_generation_manager()
        crud = self._get_pending_gen_crud() # Relies on AIGenManager or DBService being available via game_manager
        game_mngr = self._get_game_manager()

        if not ai_gen_mngr or not crud or not game_mngr or not game_mngr.db_service:
            await interaction.followup.send("Error: Core services for moderation are not available.", ephemeral=True)
            return

        try:
            async with game_mngr.db_service.get_session() as session: # Get session from DBService
                record = await crud.get_pending_generation_by_id(session, pending_id, guild_id)
                if not record:
                    await interaction.followup.send(f"No pending generation found with ID `{pending_id}` for this guild.", ephemeral=True)
                    return
                if record.status != PendingStatus.PENDING_MODERATION:
                    await interaction.followup.send(f"Generation ID `{pending_id}` is not awaiting moderation (current status: {record.status.value}). Cannot approve.", ephemeral=True)
                    return

                # Update status to APPROVED first
                updated_record = await crud.update_pending_generation_status(
                    session, record.id, PendingStatus.APPROVED, guild_id,
                    moderated_by_user_id=moderator_user_id,
                    moderator_notes="Approved via command."
                )
                await session.commit() # Commit status change to APPROVED

            if updated_record and updated_record.status == PendingStatus.APPROVED:
                logger.info(f"Generation {pending_id} approved by {moderator_user_id}. Attempting to process.")
                # Now call process_approved_generation (which will start its own transaction)
                application_success = await ai_gen_mngr.process_approved_generation(pending_id, guild_id, moderator_user_id)

                if application_success:
                    await interaction.followup.send(f"Generation ID `{pending_id}` approved and applied successfully.", ephemeral=False)
                else:
                    await interaction.followup.send(f"Generation ID `{pending_id}` was approved, but an error occurred during application/processing. Status set to APPLICATION_FAILED. Check logs.", ephemeral=True)
            else:
                await interaction.followup.send(f"Failed to update generation ID `{pending_id}` status to APPROVED. Processing not initiated.", ephemeral=True)

        except Exception as e:
            logger.error(f"Error in /master_approve_generation for ID {pending_id}: {e}", exc_info=True)
            await interaction.followup.send("An unexpected error occurred while approving the generation.", ephemeral=True)

    @app_commands.command(name="master_reject_generation", description="Rejects AI-generated content.")
    @app_commands.describe(pending_id="The ID of the pending generation to reject.", reason="Optional reason for rejection.")
    @is_master_or_admin()
    @app_commands.guild_only()
    async def reject_generation(self, interaction: Interaction, pending_id: str, reason: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        moderator_user_id = str(interaction.user.id)

        crud = self._get_pending_gen_crud()
        game_mngr = self._get_game_manager()

        if not crud or not game_mngr or not game_mngr.db_service:
            await interaction.followup.send("Error: Core services for moderation are not available.", ephemeral=True)
            return

        try:
            async with game_mngr.db_service.get_session() as session: # Use DBService for session
                record = await crud.get_pending_generation_by_id(session, pending_id, guild_id)
                if not record:
                    await interaction.followup.send(f"No pending generation found with ID `{pending_id}` for this guild.", ephemeral=True)
                    return
                if record.status not in [PendingStatus.PENDING_MODERATION, PendingStatus.FAILED_VALIDATION]:
                    await interaction.followup.send(f"Generation ID `{pending_id}` cannot be rejected (current status: {record.status.value}).", ephemeral=True)
                    return

                updated_record = await crud.update_pending_generation_status(
                    session, record.id, PendingStatus.REJECTED, guild_id,
                    moderated_by_user_id=moderator_user_id,
                    moderator_notes=reason if reason else "Rejected via command."
                )
                await session.commit()

            if updated_record and updated_record.status == PendingStatus.REJECTED:
                logger.info(f"Generation {pending_id} rejected by {moderator_user_id}. Reason: {reason or 'N/A'}")
                await interaction.followup.send(f"Generation ID `{pending_id}` has been rejected.", ephemeral=False)
            else:
                await interaction.followup.send(f"Failed to update generation ID `{pending_id}` status to REJECTED.", ephemeral=True)

        except Exception as e:
            logger.error(f"Error in /master_reject_generation for ID {pending_id}: {e}", exc_info=True)
            await interaction.followup.send("An unexpected error occurred while rejecting the generation.", ephemeral=True)


async def setup(bot: RPGBot):
    await bot.add_cog(ModerationCog(bot))
    logger.info("ModerationCog loaded.")

```
