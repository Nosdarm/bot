import discord
from discord import Interaction, app_commands
from discord.ext import commands
from typing import Optional, TYPE_CHECKING, Dict, Any, cast # Added Dict, Any, cast
import asyncio
import logging

from bot.utils.i18n_utils import get_i18n_text
from bot.game.models.action_request import ActionRequest
from bot.database.models import Player
from bot.database.crud_utils import get_entity_by_attributes, update_entity
# RPGBot will be imported conditionally for TYPE_CHECKING to avoid circular dependencies at runtime for setup
# from bot.bot_core import RPGBot

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.party_processors.party_action_processor import PartyActionProcessor
    from bot.game.models.character import Character as GameCharacter # Alias to avoid clash
    from bot.game.rules.rule_engine import RuleEngine


logger = logging.getLogger(__name__)

class ActionModuleCog(commands.Cog, name="Action Commands Module"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    async def _get_game_manager(self) -> Optional["GameManager"]:
        if hasattr(self.bot, 'game_manager') and self.bot.game_manager is not None:
            return cast("GameManager", self.bot.game_manager)
        logger.error("GameManager not available on bot instance.")
        return None

    async def _get_player_character(self, interaction: Interaction, game_mngr: "GameManager") -> Optional["GameCharacter"]:
        if not game_mngr.character_manager:
            logger.error("CharacterManager not available on GameManager.")
            return None
        if not interaction.guild_id:
            logger.error("Interaction has no guild_id.") # Should not happen for guild commands
            return None

        char = await game_mngr.character_manager.get_character_by_discord_id(str(interaction.guild_id), interaction.user.id)
        if not char:
            await interaction.followup.send("У вас нет активного персонажа.", ephemeral=True) # TODO: Localize
            return None
        return char

    @app_commands.command(name="interact", description="Взаимодействовать с объектом или NPC.")
    @app_commands.describe(target_id="ID объекта или NPC для взаимодействия.", action_type="Тип взаимодействия (если необходимо).")
    async def cmd_interact(self, interaction: Interaction, target_id: str, action_type: Optional[str] = None):
        await interaction.response.defer(ephemeral=False)

        game_mngr = await self._get_game_manager()
        if not game_mngr:
            await interaction.followup.send("GameManager не доступен.", ephemeral=True); return

        char_action_proc: Optional["CharacterActionProcessor"] = getattr(game_mngr, '_character_action_processor', None)
        if not char_action_proc:
            await interaction.followup.send("Обработчик действий персонажа не доступен.", ephemeral=True); return

        player_char = await self._get_player_character(interaction, game_mngr)
        if not player_char: return # Message already sent by helper

        if not game_mngr.rule_engine:
            lang_code = str(interaction.locale) if interaction.locale else "en"
            await interaction.followup.send(get_i18n_text(None, "error_required_modules_missing", lang_code), ephemeral=True); return # Removed default_text

        action_data_for_request = {"target_id": target_id, "interaction_type": action_type}
        action_request = ActionRequest(guild_id=str(interaction.guild_id), actor_id=player_char.id, action_type="PLAYER_INTERACT", action_data=action_data_for_request)

        rules_config_data_obj = getattr(game_mngr.rule_engine, 'rules_config_data', None)

        context_for_cap = {'channel_id': interaction.channel_id, 'rules_config': rules_config_data_obj}

        try:
            result: Optional[Dict[str, Any]] = await char_action_proc.process_action_from_request(action_request=action_request, character=player_char, context=context_for_cap)
        except Exception as e:
            logger.error(f"cmd_interact: Error calling process_action_from_request for {player_char.id} on target {target_id}: {e}", exc_info=True)
            lang_code = str(interaction.locale) if interaction.locale else getattr(player_char, 'selected_language', "en")
            error_msg_text = get_i18n_text(None, "interact_error_exception", lang_code, default_text=f"An error occurred: {e}") # Removed default_text
            await interaction.followup.send(error_msg_text, ephemeral=True)
            return

        if result and isinstance(result, dict) and result.get("message"):
            is_ephemeral = result.get("data", {}).get("ephemeral", False)
            await interaction.followup.send(result["message"], ephemeral=is_ephemeral)
        elif result and isinstance(result, dict) and not result.get("success"):
            lang_code = str(interaction.locale) if interaction.locale else getattr(player_char, 'selected_language', "en")
            error_text = get_i18n_text(None, "interact_error_generic", lang_code) # Removed default_text
            await interaction.followup.send(error_text or "Could not complete interaction.", ephemeral=True)
        elif not result:
            lang_code = str(interaction.locale) if interaction.locale else getattr(player_char, 'selected_language', "en")
            fallback_error_text = get_i18n_text(None, "interact_error_unknown", lang_code) # Removed default_text
            await interaction.followup.send(fallback_error_text or "An unknown error occurred.", ephemeral=True)

    @app_commands.command(name="fight", description="Атаковать цель (NPC или существо).")
    @app_commands.describe(target_id="ID цели для атаки.")
    async def cmd_fight(self, interaction: Interaction, target_id: str):
        await interaction.response.defer(ephemeral=False)
        game_mngr = await self._get_game_manager()
        if not game_mngr: await interaction.followup.send("GameManager не доступен.", ephemeral=True); return

        char_action_proc: Optional["CharacterActionProcessor"] = getattr(game_mngr, '_character_action_processor', None)
        if not char_action_proc: await interaction.followup.send("Обработчик действий персонажа не доступен.", ephemeral=True); return

        if not all([game_mngr.character_manager, game_mngr.npc_manager, game_mngr.combat_manager, game_mngr.rule_engine, game_mngr.location_manager]):
            await interaction.followup.send("Один или несколько модулей не доступны.", ephemeral=True); return # TODO: Localize

        player_char = await self._get_player_character(interaction, game_mngr)
        if not player_char: return

        action_data = {"target_id": target_id}
        # Assuming process_action is now process_action_from_request
        action_request = ActionRequest(guild_id=str(interaction.guild_id), actor_id=player_char.id, action_type="PLAYER_ATTACK", action_data=action_data) # Changed type
        context_for_cap = {'channel_id': interaction.channel_id, 'rules_config': getattr(game_mngr.rule_engine, 'rules_config_data', None) if game_mngr.rule_engine else None}

        try:
            # Assuming process_action_from_request for consistency
            result = await char_action_proc.process_action_from_request(action_request=action_request, character=player_char, context=context_for_cap)
            if result and isinstance(result, dict) and result.get("message"): # Handle result
                 await interaction.followup.send(result["message"], ephemeral=result.get("data", {}).get("ephemeral", False))
            elif result and isinstance(result, dict) and not result.get("success"):
                 await interaction.followup.send(result.get("message", "Failed to fight."), ephemeral=True)
            elif not result:
                 await interaction.followup.send("Unknown error during fight action.", ephemeral=True)
        except Exception as e:
            logger.error(f"cmd_fight: Error processing fight action for {player_char.id}: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while trying to fight.", ephemeral=True)


    @app_commands.command(name="talk", description="Поговорить с NPC.")
    @app_commands.describe(npc_id="ID NPC, с которым вы хотите поговорить.", message_text="Ваше первое сообщение (необязательно).")
    async def cmd_talk(self, interaction: Interaction, npc_id: str, message_text: Optional[str] = None):
        await interaction.response.defer(ephemeral=False)
        game_mngr = await self._get_game_manager()
        if not game_mngr: await interaction.followup.send("GameManager не доступен.", ephemeral=True); return

        char_action_proc: Optional["CharacterActionProcessor"] = getattr(game_mngr, '_character_action_processor', None)
        if not char_action_proc: await interaction.followup.send("Обработчик действий персонажа не доступен.", ephemeral=True); return

        if not all([game_mngr.character_manager, game_mngr.npc_manager, game_mngr.dialogue_manager, game_mngr.location_manager, game_mngr.rule_engine]):
            await interaction.followup.send("Один или несколько модулей не доступны.", ephemeral=True); return # TODO: Localize

        player_char = await self._get_player_character(interaction, game_mngr)
        if not player_char: return

        action_data_for_request = {"npc_id": npc_id, "initial_message": message_text}
        action_request = ActionRequest(guild_id=str(interaction.guild_id), actor_id=player_char.id, action_type="PLAYER_TALK", action_data=action_data_for_request)
        rules_config_data_obj = getattr(game_mngr.rule_engine, 'rules_config_data', None)
        context_for_cap = {'channel_id': interaction.channel_id, 'rules_config': rules_config_data_obj}

        try:
            result: Optional[Dict[str, Any]] = await char_action_proc.process_action_from_request(action_request=action_request, character=player_char, context=context_for_cap)
        except Exception as e:
            logger.error(f"cmd_talk: Error calling process_action_from_request for {player_char.id}: {e}", exc_info=True)
            lang_code = str(interaction.locale) if interaction.locale else getattr(player_char, 'selected_language', "en")
            error_msg_text = get_i18n_text(None, "talk_error_exception", lang_code, default_text=f"An error occurred: {e}") # Removed default_text
            await interaction.followup.send(error_msg_text, ephemeral=True)
            return

        if result and isinstance(result, dict) and result.get("message"):
            is_ephemeral = result.get("data", {}).get("ephemeral", False)
            await interaction.followup.send(result["message"], ephemeral=is_ephemeral)
        elif result and isinstance(result, dict) and not result.get("success"):
            lang_code = str(interaction.locale) if interaction.locale else getattr(player_char, 'selected_language', "en")
            error_text = get_i18n_text(None, "talk_error_generic", lang_code) # Removed default_text
            await interaction.followup.send(error_text or "Could not complete talk action.", ephemeral=True)
        elif not result:
            lang_code = str(interaction.locale) if interaction.locale else getattr(player_char, 'selected_language', "en")
            fallback_error_text = get_i18n_text(None, "talk_error_unknown", lang_code) # Removed default_text
            await interaction.followup.send(fallback_error_text or "An unknown error occurred.", ephemeral=True)

    @app_commands.command(name="end_turn", description="Завершает ход: пропускает время/передает инициативу.")
    async def cmd_end_turn(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id: await interaction.followup.send("Use in a server.", ephemeral=True); return
        guild_id_str = str(interaction.guild_id)
        discord_id_str = str(interaction.user.id)
        logger.info(f"/end_turn initiated by {discord_id_str} in guild {guild_id_str}.")

        game_mngr = await self._get_game_manager()
        if not game_mngr or not game_mngr.db_service:
            logger.error(f"/end_turn: GameManager or DBService not available for user {discord_id_str} in guild {guild_id_str}.")
            await interaction.followup.send("Game services are not available.", ephemeral=True); return

        db_session_factory = getattr(game_mngr.db_service, 'get_session', None)
        if not callable(db_session_factory):
            logger.error(f"/end_turn: DBService.get_session not available or not callable for user {discord_id_str} in guild {guild_id_str}.")
            await interaction.followup.send("Database session error.", ephemeral=True); return

        try:
            async with db_session_factory() as session: # type: ignore[operator] # Pyright might not know it's async context manager
                player = await get_entity_by_attributes(session, Player, {"discord_id": discord_id_str, "guild_id": guild_id_str}) # Added guild_id to query
                if not player:
                    logger.warning(f"/end_turn: Player not found for discord_id {discord_id_str} in guild {guild_id_str}.")
                    await interaction.followup.send("Player not found.", ephemeral=True); return # TODO: Localize

                player.current_game_status = "actions_submitted"
                await update_entity(session, player, {"current_game_status": "actions_submitted"}) # Pass guild_id if update_entity requires it
                await session.commit() # type: ignore[attr-defined] # Assuming session has commit
                logger.info(f"/end_turn: Player {player.id} status updated to 'actions_submitted'.")

            await interaction.followup.send("You have ended your turn.", ephemeral=True) # TODO: Localize
        except Exception as e:
            logger.error(f"Error in /end_turn for {discord_id_str}: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while ending your turn.", ephemeral=True)

    @app_commands.command(name="end_party_turn", description="ГМ: Завершить ход для всей текущей активной партии.")
    async def cmd_end_party_turn(self, interaction: Interaction):
        game_mngr = await self._get_game_manager()
        if not game_mngr or not hasattr(game_mngr, '_settings') or game_mngr._settings is None: # type: ignore[attr-defined]
            await interaction.response.send_message("Game settings not available.", ephemeral=True); return

        bot_admin_ids = [str(id_val) for id_val in game_mngr._settings.get('bot_admins', [])] # type: ignore[attr-defined]
        if str(interaction.user.id) not in bot_admin_ids:
             await interaction.response.send_message("Только Мастер может использовать эту команду.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)

        party_action_proc: Optional["PartyActionProcessor"] = getattr(game_mngr, 'party_action_processor', None) # type: ignore[attr-defined]
        if not party_action_proc:
            await interaction.followup.send("Обработчик действий партии не доступен.", ephemeral=True); return

        result_dict: Optional[Dict[str, Any]] = await party_action_proc.gm_force_end_party_turn(
            guild_id=str(interaction.guild_id),
            context={'game_manager': game_mngr, 'send_to_command_channel': interaction.followup.send}
        )
        if result_dict and isinstance(result_dict, dict) and result_dict.get("message"):
            await interaction.followup.send(str(result_dict.get("message")), ephemeral=True) # Ensure message is str
        elif not result_dict or not result_dict.get("success"):
            msg_content = "Не удалось завершить ход партии."
            if result_dict and isinstance(result_dict, dict) and result_dict.get("message"):
                msg_content = str(result_dict.get("message")) # Ensure message is str
            await interaction.followup.send(msg_content, ephemeral=True)

async def setup(bot: 'RPGBot'): # Changed BotCore to RPGBot, and quoted RPGBot
    await bot.add_cog(ActionModuleCog(bot))
    print("ActionModuleCog loaded.")
