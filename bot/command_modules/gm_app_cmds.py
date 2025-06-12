import discord # Ensure discord is imported for discord.Interaction
from discord import Interaction, app_commands
from discord.ext import commands
import traceback
from bot.command_modules.game_setup_cmds import is_master_or_admin_check
from bot.command_modules.game_setup_cmds import is_master_or_admin_check
import json # For parsing parameters_json
from typing import TYPE_CHECKING, Optional, Dict, Any # For type hints

from bot.game.managers.undo_manager import UndoManager # Make it a runtime import

if TYPE_CHECKING:
    from bot.bot_core import RPGBot # For type hinting self.bot
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.party_manager import PartyManager
    # from bot.game.conflict_resolver import ConflictResolver (already on GameManager)

class GMAppCog(commands.Cog, name="GM App Commands"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    @app_commands.command(name="gm_simulate", description="ГМ: Запустить один шаг симуляции мира.")
    async def cmd_gm_simulate(self, interaction: Interaction):
        # This command was standalone in bot_core.py
        # GM Check (simplified from game_setup_cmds for now)
        # Ensure game_manager and settings are accessible
        if not hasattr(self.bot, 'game_manager') or not self.bot.game_manager or not hasattr(self.bot.game_manager, '_settings'):
            await interaction.response.send_message("**Мастер:** Конфигурация игры не загружена.", ephemeral=True)
            return

        bot_admin_ids = [str(id_val) for id_val in self.bot.game_manager._settings.get('bot_admins', [])]
        if str(interaction.user.id) not in bot_admin_ids:
            await interaction.response.send_message("**Мастер:** Только Истинный Мастер может управлять ходом времени!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("**Мастер:** Эту команду можно использовать только на сервере.", ephemeral=True)
            return

        game_mngr = self.bot.game_manager
        if game_mngr:
            try:
                # Assuming trigger_manual_simulation_tick is on GameManager
                await game_mngr.trigger_manual_simulation_tick(server_id=str(interaction.guild_id)) # Ensure guild_id is string
                await interaction.followup.send("**Мастер:** Шаг симуляции мира (ручной) завершен!")
            except Exception as e:
                print(f"Error in cmd_gm_simulate (Cog): {e}")
                traceback.print_exc()
                await interaction.followup.send(f"**Мастер:** Ошибка при симуляции: {e}", ephemeral=True)
        else:
            await interaction.followup.send("**Мастер:** GameManager недоступен.", ephemeral=True)

    # Correctly indented as a method of GMAppCog
    @app_commands.command(name="resolve_conflict", description="ГМ: Разрешить ожидающий конфликт.")
    @app_commands.describe(
        conflict_id="ID ожидающего конфликта для разрешения.",
        outcome_type="Тип выбранного исхода (согласно правилам конфликта).",
        parameters_json="JSON строка с дополнительными параметрами для исхода (если требуется)."
    )
    async def cmd_resolve_conflict(
        self,
        interaction: discord.Interaction,
        conflict_id: str,
        outcome_type: str,
        parameters_json: Optional[str] = None
    ):
        # GM/Admin Check
        if not hasattr(self.bot, 'game_manager') or not self.bot.game_manager or not hasattr(self.bot.game_manager, '_settings'):
            await interaction.response.send_message("**Мастер:** Конфигурация игры не загружена.", ephemeral=True)
            return

        # Assuming self.bot.game_manager is GameManager instance
        game_mngr = self.bot.game_manager

        bot_admin_ids = [str(id_val) for id_val in game_mngr._settings.get('bot_admins', [])]
        if str(interaction.user.id) not in bot_admin_ids:
            await interaction.response.send_message("**Мастер:** Только Истинный Мастер может разрешать конфликты!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True) # Defer response as processing might take time

        if not game_mngr or not game_mngr.conflict_resolver:
            await interaction.followup.send("**Мастер:** Система разрешения конфликтов недоступна.", ephemeral=True)
            return

        parsed_params: Optional[Dict[str, Any]] = None
        if parameters_json:
            try:
                parsed_params = json.loads(parameters_json)
                if not isinstance(parsed_params, dict):
                    await interaction.followup.send("**Мастер:** Ошибка: 'parameters_json' должен быть словарем (JSON object).", ephemeral=True)
                    return
            except json.JSONDecodeError as e:
                await interaction.followup.send(f"**Мастер:** Ошибка парсинга JSON параметров: {e}", ephemeral=True)
                return

        try:
            # Assuming game_mngr.conflict_resolver is ConflictResolver instance
            resolution_result = await game_mngr.conflict_resolver.process_master_resolution(
                conflict_id=conflict_id,
                outcome_type=outcome_type,
                params=parsed_params
            )

            response_message_content = ""
            if resolution_result.get("success"):
                response_message_content = f"Конфликт '{conflict_id}' успешно разрешен как '{outcome_type}'.\n"
                response_message_content += resolution_result.get("message", "Детали не предоставлены.")
                # Log GM action
                if game_mngr.game_log_manager and interaction.guild_id:
                    try:
                        await game_mngr.game_log_manager.log_event(
                            guild_id=str(interaction.guild_id),
                            event_type="gm_action_resolve_conflict",
                            message=f"GM {interaction.user.name} ({interaction.user.id}) resolved conflict {conflict_id} as {outcome_type}.",
                            metadata={"conflict_id": conflict_id, "outcome": outcome_type, "params": parsed_params, "resolver_user_id": str(interaction.user.id)}
                        )
                    except Exception as log_e:
                        print(f"Error logging GM conflict resolution: {log_e}")

            else:
                response_message_content = f"Ошибка разрешения конфликта '{conflict_id}':\n"
                response_message_content += resolution_result.get("message", "Неизвестная ошибка.")

            await interaction.followup.send(f"**Мастер:** {response_message_content}", ephemeral=True)

        except Exception as e:
            print(f"Error in cmd_resolve_conflict: {e}")
            traceback.print_exc()
            await interaction.followup.send(f"**Мастер:** Произошла серьезная ошибка при обработке разрешения конфликта: {e}", ephemeral=True)
# Make sure this method is part of the class by proper indentation

    @app_commands.command(name="gm_delete_character", description="ГМ: Удалить данные персонажа по его ID.")
    @app_commands.describe(character_id="ID персонажа (Character object UUID) для удаления.")
    async def cmd_gm_delete_character(self, interaction: discord.Interaction, character_id: str):
        if not interaction.guild_id:
            await interaction.response.send_message("Эта команда должна быть использована на сервере.", ephemeral=True)
            return

        # GM Check using the imported helper
        if not await is_master_or_admin_check(interaction):
            await interaction.response.send_message("**Мастер:** Только истинный Мастер или администратор может удалять персонажей!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.character_manager:
            await interaction.followup.send("**Мастер:** CharacterManager недоступен.", ephemeral=True)
            return

        try:
            # Ensure guild_id is a string for the remove_character method
            guild_id_str = str(interaction.guild_id)

            # Call the existing remove_character method in CharacterManager
            # This method handles removing from cache, marking for DB deletion, and associated cleanup.
            removed_char_id = await game_mngr.character_manager.remove_character(
                character_id=character_id,
                guild_id=guild_id_str
                # Optional: pass interaction or other context if remove_character can use it
            )

            if removed_char_id:
                response_message = f"Персонаж с ID '{removed_char_id}' был помечен для удаления. Данные будут удалены из БД при следующем сохранении."
                # Log GM action
                if game_mngr.game_log_manager:
                    try:
                        await game_mngr.game_log_manager.log_event(
                            guild_id=guild_id_str,
                            event_type="gm_action_delete_character",
                            message=f"GM {interaction.user.name} ({interaction.user.id}) initiated deletion for character ID {character_id}.",
                            metadata={"character_id": character_id, "deleter_user_id": str(interaction.user.id)}
                        )
                    except Exception as log_e:
                        print(f"Error logging GM character deletion: {log_e}")
                await interaction.followup.send(f"**Мастер:** {response_message}", ephemeral=True)
            else:
                # This might happen if the character_id was not found in the cache for that guild
                await interaction.followup.send(f"**Мастер:** Не удалось найти персонажа с ID '{character_id}' в указанной гильдии для удаления. Возможно, он уже удален или ID неверен.", ephemeral=True)

        except Exception as e:
            print(f"Error in cmd_gm_delete_character: {e}")
            traceback.print_exc()
            await interaction.followup.send(f"**Мастер:** Произошла ошибка при удалении персонажа: {e}", ephemeral=True)

    @app_commands.command(name="master_undo", description="ГМ: Отменить последнее событие для игрока или партии.")
    @app_commands.describe(
        num_steps="Количество последних событий для отмены (по умолчанию 1).",
        entity_id="ID игрока или партии, для которого отменяются события. Если не указано, действие не будет выполнено."
    )
    async def cmd_master_undo(self, interaction: Interaction, num_steps: Optional[int] = 1, entity_id: Optional[str] = None):
        if not await is_master_or_admin_check(interaction):
            await interaction.response.send_message("**Мастер:** Только Мастера Игры могут использовать эту команду.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("**Мастер:** Эту команду можно использовать только на сервере.", ephemeral=True)
            return
        guild_id_str = str(interaction.guild_id)

        if num_steps is None or num_steps < 1:
            num_steps = 1

        game_mngr: GameManager = self.bot.game_manager
        if not game_mngr:
            await interaction.followup.send("**Мастер:** GameManager недоступен.", ephemeral=True)
            return

        undo_manager: Optional[UndoManager] = getattr(game_mngr, 'undo_manager', None)
        if not undo_manager:
            await interaction.followup.send("**Мастер:** UndoManager недоступен.", ephemeral=True)
            return

        character_manager: Optional[CharacterManager] = game_mngr.character_manager
        party_manager: Optional[PartyManager] = game_mngr.party_manager

        if not entity_id:
            await interaction.followup.send("**Мастер:** Guild-wide undo без указания ID игрока или партии не поддерживается. Пожалуйста, укажите ID.", ephemeral=True)
            return

        success = False
        action_type = "unknown"

        if character_manager:
            # Check if entity_id is a player
            # Assuming get_character is synchronous or we have an async version
            # For now, assuming synchronous get_character from cache for this check
            char = character_manager.get_character(guild_id_str, entity_id)
            if char:
                action_type = "player"
                success = await undo_manager.undo_last_player_event(guild_id_str, entity_id, num_steps)

        if not success and party_manager: # If not found as player or player undo failed, try party
            # Check if entity_id is a party
            # Assuming get_party is synchronous or we have an async version
            party = party_manager.get_party(guild_id_str, entity_id)
            if party:
                action_type = "party"
                success = await undo_manager.undo_last_party_event(guild_id_str, entity_id, num_steps)

        if action_type == "unknown":
            await interaction.followup.send(f"**Мастер:** Сущность с ID '{entity_id}' не найдена как игрок или партия.", ephemeral=True)
            return

        if success:
            await interaction.followup.send(f"**Мастер:** Последние {num_steps} событий для {action_type} '{entity_id}' были успешно отменены.", ephemeral=True)
        else:
            await interaction.followup.send(f"**Мастер:** Не удалось отменить события для {action_type} '{entity_id}'. Проверьте логи для деталей.", ephemeral=True)


    @app_commands.command(name="master_goto_log", description="ГМ: Отменить события до указанной записи в логе.")
    @app_commands.describe(
        log_id_target="ID записи лога, до которой (не включая) нужно отменить события.",
        entity_id="Опционально: ID игрока или партии, для которого выполняется откат. Если не указано, откат затрагивает все события гильдии."
    )
    async def cmd_master_goto_log(self, interaction: Interaction, log_id_target: str, entity_id: Optional[str] = None):
        if not await is_master_or_admin_check(interaction):
            await interaction.response.send_message("**Мастер:** Только Мастера Игры могут использовать эту команду.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("**Мастер:** Эту команду можно использовать только на сервере.", ephemeral=True)
            return
        guild_id_str = str(interaction.guild_id)

        game_mngr: GameManager = self.bot.game_manager
        if not game_mngr:
            await interaction.followup.send("**Мастер:** GameManager недоступен.", ephemeral=True)
            return

        undo_manager: Optional[UndoManager] = getattr(game_mngr, 'undo_manager', None)
        if not undo_manager:
            await interaction.followup.send("**Мастер:** UndoManager недоступен.", ephemeral=True)
            return

        character_manager: Optional[CharacterManager] = game_mngr.character_manager
        party_manager: Optional[PartyManager] = game_mngr.party_manager

        entity_type_str: Optional[str] = None
        if entity_id:
            if character_manager and character_manager.get_character(guild_id_str, entity_id):
                entity_type_str = "player"
            elif party_manager and party_manager.get_party(guild_id_str, entity_id):
                entity_type_str = "party"
            else:
                await interaction.followup.send(f"**Мастер:** Сущность с ID '{entity_id}' не найдена как игрок или партия. Откат будет применен ко всем событиям гильдии до указанного лога.", ephemeral=True)
                # Proceeding with entity_id=None and entity_type_str=None for guild-wide if GM confirms or if this is desired behavior
                # For safety, if entity_id was provided but not found, one might choose to abort.
                # Current logic: if entity_id is given but not found, it proceeds as guild-wide.
                # Let's refine: if entity_id is given but not found, it's an error for that entity.
                # If entity_id is NOT given, it's guild-wide (which we might restrict).
                # For now, if entity_id is given and not found, let's send an error and stop.
                await interaction.followup.send(f"**Мастер:** Сущность с ID '{entity_id}' не найдена. Укажите корректный ID игрока/партии или не указывайте ID для отката всех событий гильдии (с осторожностью).", ephemeral=True)
                return


        success = await undo_manager.undo_to_log_entry(
            guild_id_str,
            log_id_target,
            player_or_party_id=entity_id,
            entity_type=entity_type_str
        )

        if success:
            message = f"**Мастер:** События успешно отменены до записи лога '{log_id_target}'."
            if entity_id:
                message += f" Для сущности ({entity_type_str}) '{entity_id}'."
            else:
                message += " Для всей гильдии."
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.followup.send(f"**Мастер:** Не удалось отменить события до записи лога '{log_id_target}'. Проверьте логи.", ephemeral=True)

    @app_commands.command(name="master_undo_event", description="ГМ: Отменить конкретное событие по его ID из лога.")
    @app_commands.describe(log_id="ID записи лога для отмены.")
    async def cmd_master_undo_event(self, interaction: Interaction, log_id: str):
        if not await is_master_or_admin_check(interaction):
            await interaction.response.send_message("**Мастер:** Только Мастера Игры могут использовать эту команду.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("**Мастер:** Эту команду можно использовать только на сервере.", ephemeral=True)
            return
        guild_id_str = str(interaction.guild_id)

        game_mngr: GameManager = self.bot.game_manager
        if not game_mngr:
            await interaction.followup.send("**Мастер:** GameManager недоступен.", ephemeral=True)
            return

        undo_manager: Optional[UndoManager] = getattr(game_mngr, 'undo_manager', None)
        if not undo_manager:
            await interaction.followup.send("**Мастер:** UndoManager недоступен.", ephemeral=True)
            return

        if not log_id:
            await interaction.followup.send("**Мастер:** ID лога не указан.", ephemeral=True)
            return

        success = await undo_manager.undo_specific_log_entry(guild_id_str, log_id)

        if success:
            await interaction.followup.send(f"**Мастер:** Событие с ID лога '{log_id}' было успешно отменено и удалено из истории.", ephemeral=True)
        else:
            await interaction.followup.send(f"**Мастер:** Не удалось отменить событие с ID лога '{log_id}'. Проверьте серверные логи для деталей. Возможно, лог не найден или тип события не подлежит отмене.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GMAppCog(bot)) # type: ignore
    print("GMAppCog loaded.")
