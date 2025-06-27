import discord
from discord import Interaction, app_commands
from discord.ext import commands
import traceback
import logging
import json
from typing import TYPE_CHECKING, Optional, Dict, Any, List, cast

from bot.game.managers.undo_manager import UndoManager # Keep if used, seems so

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.api.schemas.rule_config_schemas import RuleConfigData
    import datetime
    from sqlalchemy.ext.asyncio import AsyncSession
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.database.models.pending_generation import PendingGeneration, PendingStatus
    from bot.ai.ai_response_validator import parse_and_validate_ai_response
    from bot.ai.ai_data_models import GenerationType


from bot.utils.decorators import is_master_role


class GMAppCog(commands.Cog, name="GM App Commands"):
    master_group = app_commands.Group(name="master", description="Команды для Мастера Игры.", guild_only=True)

    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    class SimpleReportFormatter:
        def __init__(self, game_manager: "GameManager", guild_id: str):
            self.game_manager = game_manager
            self.guild_id = guild_id

        async def _get_entity_name(self, entity_id: str, entity_type: str, lang: str) -> str:
            name = entity_id
            # Ensure managers are not None before accessing them
            if entity_type == "location" and self.game_manager and self.game_manager.location_manager:
                loc = await self.game_manager.location_manager.get_location_instance(self.guild_id, entity_id)
                if loc: name = getattr(loc, "name_i18n", {}).get(lang, getattr(loc, "name_i18n", {}).get("en", loc.id)) if hasattr(loc,"name_i18n") else getattr(loc,"name", loc.id)
            elif entity_type == "npc" and self.game_manager and self.game_manager.npc_manager:
                npc = await self.game_manager.npc_manager.get_npc(self.guild_id, entity_id)
                if npc: name = npc.name_i18n.get(lang,npc.name_i18n.get("en",npc.id)) if hasattr(npc,"name_i18n") and npc.name_i18n else getattr(npc,"name",npc.id)
            elif entity_type == "character" and self.game_manager and self.game_manager.character_manager:
                char = await self.game_manager.character_manager.get_character(self.guild_id, entity_id)
                if char: name = (char.name_i18n.get(lang,char.name_i18n.get("en",char.id)) if hasattr(char,"name_i18n") and char.name_i18n else getattr(char,"name",char.id))
            elif entity_type == "event" and self.game_manager and self.game_manager.event_manager:
                evt = await self.game_manager.event_manager.get_event(self.guild_id, entity_id)
                if evt: name = getattr(evt, "name", evt.id)
            return name

    @app_commands.command(name="gm_simulate", description="ГМ: Запустить один шаг симуляции мира.")
    @is_master_role()
    async def cmd_gm_simulate(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id:
            await interaction.followup.send("**Мастер:** Эту команду можно использовать только на сервере.", ephemeral=True)
            return

        game_mngr: Optional["GameManager"] = self.bot.game_manager
        if game_mngr:
            try:
                # Ensure the method exists and is callable before trying to await it
                if hasattr(game_mngr, 'trigger_manual_simulation_tick') and callable(getattr(game_mngr, 'trigger_manual_simulation_tick')):
                    await game_mngr.trigger_manual_simulation_tick(server_id=str(interaction.guild_id))
                    await interaction.followup.send("**Мастер:** Шаг симуляции мира (ручной) завершен!")
                else:
                    logging.warning("GameManager does not have a callable 'trigger_manual_simulation_tick' method.")
                    await interaction.followup.send("**Мастер:** Функция симуляции недоступна.", ephemeral=True)
            except Exception as e:
                logging.exception(f"Error in cmd_gm_simulate (Cog) for guild {interaction.guild_id}")
                await interaction.followup.send(f"**Мастер:** Ошибка при симуляции: {e}", ephemeral=True)
        else:
            await interaction.followup.send("**Мастер:** GameManager недоступен.", ephemeral=True)

    @app_commands.command(name="resolve_conflict", description="ГМ: Разрешить ожидающий конфликт.")
    @app_commands.describe(conflict_id="ID конфликта.", outcome_type="Тип исхода.", parameters_json="JSON параметры (опц).")
    @is_master_role()
    async def cmd_resolve_conflict(self, interaction: discord.Interaction, conflict_id: str, outcome_type: str, parameters_json: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id:
            await interaction.followup.send("**Мастер:** Команда для сервера.", ephemeral=True)
            return

        game_mngr: Optional["GameManager"] = self.bot.game_manager
        if not game_mngr or not hasattr(game_mngr, 'conflict_resolver') or not game_mngr.conflict_resolver or \
           not hasattr(game_mngr, 'game_log_manager') or not game_mngr.game_log_manager:
            await interaction.followup.send("**Мастер:** ConflictResolver/GameLogManager недоступен.", ephemeral=True)
            return

        parsed_params = None
        if parameters_json:
            try:
                parsed_params = json.loads(parameters_json)
            except json.JSONDecodeError as e:
                await interaction.followup.send(f"**Мастер:** Ошибка JSON: {e}", ephemeral=True)
                return
            if not isinstance(parsed_params, dict):
                await interaction.followup.send("**Мастер:** JSON должен быть объектом.", ephemeral=True)
                return
        try:
            res = {"success": False, "message": "Неизвестная ошибка."}
            if hasattr(game_mngr.conflict_resolver, 'process_master_resolution') and callable(game_mngr.conflict_resolver.process_master_resolution): # type: ignore[attr-defined]
                res = await game_mngr.conflict_resolver.process_master_resolution(conflict_id, outcome_type, parsed_params) # type: ignore[attr-defined]
            else:
                logging.warning(f"ConflictResolver for guild {interaction.guild_id} missing 'process_master_resolution'.")
                res['message'] = "Функция разрешения конфликтов недоступна."

            msg = f"Конфликт '{conflict_id}' разрешен как '{outcome_type}'.\n{res.get('message','Детали не предоставлены.')}" if res.get("success") else f"Ошибка разрешения '{conflict_id}':\n{res.get('message','Неизвестная ошибка.')}"
            if res.get("success") and game_mngr.game_log_manager and hasattr(game_mngr.game_log_manager, 'log_event') and callable(game_mngr.game_log_manager.log_event): # type: ignore[attr-defined]
                log_d = {"conflict_id":conflict_id,"outcome":outcome_type,"params":parsed_params,"gm_id":str(interaction.user.id),"gm_name":interaction.user.name, "desc_msg": f"GM {interaction.user.name} resolved conflict {conflict_id} as {outcome_type}."}
                await game_mngr.game_log_manager.log_event(str(interaction.guild_id),"gm_action_resolve_conflict",details=log_d) # type: ignore[attr-defined]
            await interaction.followup.send(f"**Мастер:** {msg}", ephemeral=True)
        except Exception as e:
            logging.error(f"Error in cmd_resolve_conflict: {e}", exc_info=True)
            await interaction.followup.send(f"**Мастер:** Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="gm_delete_character", description="ГМ: Удалить данные персонажа по его ID.")
    @app_commands.describe(character_id="ID персонажа (Character object UUID) для удаления.")
    @is_master_role()
    async def cmd_gm_delete_character(self, interaction: discord.Interaction, character_id: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id:
            await interaction.followup.send("**Мастер:** Команда для сервера.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        game_mngr: Optional["GameManager"] = self.bot.game_manager
        if not game_mngr or not hasattr(game_mngr, 'character_manager') or not game_mngr.character_manager or \
           not hasattr(game_mngr, 'game_log_manager') or not game_mngr.game_log_manager:
            await interaction.followup.send("**Мастер:** CharacterManager/GameLogManager недоступен.", ephemeral=True)
            return

        try:
            removed_char_id = None
            if hasattr(game_mngr.character_manager, 'remove_character') and callable(getattr(game_mngr.character_manager, 'remove_character')):
                removed_char_id = await game_mngr.character_manager.remove_character(character_id, guild_id_str)
            else:
                logging.warning(f"CharacterManager for guild {guild_id_str} does not have a callable 'remove_character' method.")
                removed_char_id = None

            if removed_char_id:
                if game_mngr.game_log_manager and hasattr(game_mngr.game_log_manager, 'log_event') and callable(getattr(game_mngr.game_log_manager, 'log_event')):
                    log_d = {"char_id":character_id,"deleter_gm_id":str(interaction.user.id),"deleter_gm_name":interaction.user.name, "desc_msg":f"GM {interaction.user.name} initiated deletion for char ID {character_id}."}
                    await game_mngr.game_log_manager.log_event(guild_id_str,"gm_action_delete_character",details=log_d)
                    await interaction.followup.send(f"**Мастер:** Персонаж '{removed_char_id}' помечен для удаления.", ephemeral=True)
                else:
                    logging.warning(f"GameLogManager unavailable or log_event missing for character deletion log in guild {guild_id_str}.")
                    await interaction.followup.send(f"**Мастер:** Персонаж '{removed_char_id}' помечен для удаления (ошибка логирования).", ephemeral=True)
            else:
                await interaction.followup.send(f"**Мастер:** Персонаж '{character_id}' не найден/не удален, или метод удаления недоступен.", ephemeral=True)
        except Exception as e:
            logging.exception(f"Error in cmd_gm_delete_character for character {character_id} in guild {guild_id_str}")
            await interaction.followup.send(f"**Мастер:** Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="master_undo", description="ГМ: Отменить последнее событие для игрока или партии.")
    @app_commands.describe(num_steps="Количество шагов (по умолчанию 1).", entity_id="ID игрока/партии (обязательно).")
    @is_master_role()
    async def cmd_master_undo(self, interaction: Interaction, num_steps: Optional[int] = 1, entity_id: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id:
            await interaction.followup.send("**Мастер:** Команда для сервера.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        game_mngr: Optional["GameManager"] = self.bot.game_manager
        if not game_mngr or not hasattr(game_mngr, 'undo_manager') or not game_mngr.undo_manager or \
           not hasattr(game_mngr, 'character_manager') or not game_mngr.character_manager or \
           not hasattr(game_mngr, 'party_manager') or not game_mngr.party_manager:
            await interaction.followup.send("**Мастер:** UndoManager/CharacterManager/PartyManager недоступен.", ephemeral=True)
            return

        if not entity_id:
            await interaction.followup.send("**Мастер:** ID игрока/партии обязателен.", ephemeral=True)
            return

        num_steps_val = num_steps if num_steps and num_steps >= 1 else 1
        action_type, success = "unknown", False

        char_obj = await game_mngr.character_manager.get_character(guild_id_str, entity_id)
        party_obj = await game_mngr.party_manager.get_party(guild_id_str, entity_id)

        if char_obj:
            action_type="player"
            if hasattr(game_mngr.undo_manager, 'undo_last_player_event') and callable(getattr(game_mngr.undo_manager, 'undo_last_player_event')) :
                success = await game_mngr.undo_manager.undo_last_player_event(guild_id_str, entity_id, num_steps_val)
        elif party_obj:
            action_type="party"
            if hasattr(game_mngr.undo_manager, 'undo_last_party_event') and callable(getattr(game_mngr.undo_manager, 'undo_last_party_event')):
                success = await game_mngr.undo_manager.undo_last_party_event(guild_id_str, entity_id, num_steps_val)

        if action_type=="unknown":
            await interaction.followup.send(f"**Мастер:** Сущность '{entity_id}' не найдена.", ephemeral=True)
            return

        msg = f"**Мастер:** Последние {num_steps_val} событий для {action_type} '{entity_id}' {'отменены' if success else 'не удалось отменить'}."
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="master_goto_log", description="ГМ: Отменить события до указанной записи лога.")
    @app_commands.describe(log_id_target="ID целевой записи лога.", entity_id="Опц: ID игрока/партии.")
    @is_master_role()
    async def cmd_master_goto_log(self, interaction: Interaction, log_id_target: str, entity_id: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id:
            await interaction.followup.send("**Мастер:** Команда для сервера.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        game_mngr: Optional["GameManager"] = self.bot.game_manager
        if not game_mngr or not hasattr(game_mngr, 'undo_manager') or not game_mngr.undo_manager:
            await interaction.followup.send("**Мастер:** UndoManager недоступен.", ephemeral=True)
            return

        entity_type_str: Optional[str] = None
        success = False
        if entity_id:
            if hasattr(game_mngr, 'character_manager') and game_mngr.character_manager and \
               await game_mngr.character_manager.get_character(guild_id_str, entity_id): # type: ignore[attr-defined] # Add await
                entity_type_str="player"
            elif hasattr(game_mngr, 'party_manager') and game_mngr.party_manager and \
                  await game_mngr.party_manager.get_party(guild_id_str, entity_id): # type: ignore[attr-defined] # Add await
                entity_type_str="party"
            else:
                await interaction.followup.send(f"**Мастер:** Сущность '{entity_id}' не найдена.", ephemeral=True)
                return

        if hasattr(game_mngr.undo_manager, 'undo_to_log_entry') and callable(getattr(game_mngr.undo_manager, 'undo_to_log_entry')):
            success = await game_mngr.undo_manager.undo_to_log_entry(guild_id_str, log_id_target, entity_id, entity_type_str)
        msg = f"**Мастер:** События до лога '{log_id_target}'" + (f" для '{entity_id}'" if entity_id else " для гильдии")
        await interaction.followup.send(f"{msg} {'успешно отменены' if success else 'не удалось отменить'}.", ephemeral=True)

    @app_commands.command(name="master_undo_event", description="ГМ: Отменить конкретное событие по ID из лога.")
    @app_commands.describe(log_id="ID записи лога для отмены.")
    @is_master_role()
    async def cmd_master_undo_event(self, interaction: Interaction, log_id: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id:
            await interaction.followup.send("**Мастер:** Команда для сервера.", ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        game_mngr: Optional["GameManager"] = self.bot.game_manager
        if not game_mngr or not hasattr(game_mngr, 'undo_manager') or not game_mngr.undo_manager:
            await interaction.followup.send("**Мастер:** UndoManager недоступен.", ephemeral=True)
            return

        if not log_id:
            await interaction.followup.send("**Мастер:** ID лога не указан.", ephemeral=True)
            return
        success = False
        if hasattr(game_mngr.undo_manager, 'undo_specific_log_entry') and callable(getattr(game_mngr.undo_manager, 'undo_specific_log_entry')):
            success = await game_mngr.undo_manager.undo_specific_log_entry(guild_id_str, log_id)
        await interaction.followup.send(f"**Мастер:** Событие '{log_id}' {'успешно отменено' if success else 'не удалось отменить'}.", ephemeral=True)

    @app_commands.command(name="master_edit_npc", description="ГМ: Редактировать атрибут NPC.")
    @app_commands.describe(npc_id="ID NPC для редактирования.",
                           attribute="Атрибут для изменения (например, name_i18n.en, stats.hp, location_id).",
                           value="Новое значение для атрибута.")
    @is_master_role()
    async def cmd_master_edit_npc(self, interaction: Interaction, npc_id: str, attribute: str, value: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = str(interaction.guild_id)
        game_mngr: Optional["GameManager"] = self.bot.game_manager

        if not game_mngr or not hasattr(game_mngr, 'npc_manager') or not game_mngr.npc_manager or \
           not hasattr(game_mngr, 'game_log_manager') or not game_mngr.game_log_manager:
            await interaction.followup.send("**Мастер:** NpcManager или GameLogManager недоступен.", ephemeral=True)
            return

        npc = await game_mngr.npc_manager.get_npc(guild_id, npc_id)
        if not npc:
            await interaction.followup.send(f"**Мастер:** NPC с ID '{npc_id}' не найден.", ephemeral=True)
            return

        try:
            original_value_str = "N/A"
            processed_value: Any = value
            log_value = value
            default_lang = "en"

            if hasattr(game_mngr, "get_default_bot_language") and callable(getattr(game_mngr, "get_default_bot_language")):
                lang_result = await game_mngr.get_default_bot_language(guild_id)
                if lang_result: default_lang = lang_result

            lang_for_log = str(interaction.locale or default_lang)

            npc_name_for_log = npc.id
            if hasattr(npc, 'name_i18n') and isinstance(npc.name_i18n, dict):
                npc_name_for_log = npc.name_i18n.get(lang_for_log, npc.name_i18n.get("en", npc.id))
            elif hasattr(npc, 'name'):
                npc_name_for_log = npc.name

            update_successful = False

            if attribute.startswith("name_i18n.") or \
               attribute.startswith("description_i18n.") or \
               attribute.startswith("persona_i18n."):
                parts = attribute.split(".", 1)
                field_name = parts[0]
                lang_code = parts[1]

                if not hasattr(npc, field_name):
                    await interaction.followup.send(f"**Мастер:** У NPC нет атрибута '{field_name}'.", ephemeral=True)
                    return

                current_i18n_dict = getattr(npc, field_name, {})
                if not isinstance(current_i18n_dict, dict): current_i18n_dict = {}

                original_value_str = str(current_i18n_dict.get(lang_code, "N/A"))
                current_i18n_dict[lang_code] = value
                processed_value = current_i18n_dict

                if hasattr(game_mngr.npc_manager, 'update_npc_field') and callable(getattr(game_mngr.npc_manager, 'update_npc_field')) :
                    update_successful = await game_mngr.npc_manager.update_npc_field(guild_id, npc_id, field_name, processed_value)
                else:
                    logging.warning(f"NpcManager for guild {guild_id} does not have a callable 'update_npc_field' method. Falling back to setattr.")
                    setattr(npc, field_name, processed_value)
                    if hasattr(game_mngr.npc_manager, 'mark_npc_dirty') and callable(getattr(game_mngr.npc_manager, 'mark_npc_dirty')):
                        await game_mngr.npc_manager.mark_npc_dirty(guild_id, npc_id)
                    update_successful = True
                log_value = f"{value} (lang: {lang_code})"

            elif attribute.startswith("stats."):
                stat_key = attribute.split(".", 1)[1]
                current_stats = npc.stats if isinstance(npc.stats, dict) else {}
                original_value_str = str(current_stats.get(stat_key, "N/A"))
                target_type = None
                if stat_key in current_stats and current_stats[stat_key] is not None:
                    target_type = type(current_stats[stat_key])

                if target_type == bool: processed_value = value.lower() in ['true', '1', 'yes']
                elif target_type == int:
                    try: processed_value = int(value)
                    except ValueError: await interaction.followup.send(f"**Мастер:** Неверное значение для '{attribute}'. Ожидалось целое.", ephemeral=True); return
                elif target_type == float:
                    try: processed_value = float(value)
                    except ValueError: await interaction.followup.send(f"**Мастер:** Неверное значение для '{attribute}'. Ожидалось число.", ephemeral=True); return
                else: # Attempt to infer type if not explicitly known or if target_type is None
                    try: processed_value = int(value)
                    except ValueError:
                        try: processed_value = float(value)
                        except ValueError: processed_value = value

                if hasattr(game_mngr.npc_manager, 'update_npc_stats') and callable(getattr(game_mngr.npc_manager, 'update_npc_stats')):
                    update_successful = await game_mngr.npc_manager.update_npc_stats(guild_id, npc_id, {stat_key: processed_value})
                else:
                    logging.warning(f"NpcManager for guild {guild_id} does not have a callable 'update_npc_stats' method. Falling back to direct modification.")
                    current_stats[stat_key] = processed_value
                    setattr(npc, 'stats', current_stats)
                    if hasattr(game_mngr.npc_manager, 'mark_npc_dirty') and callable(getattr(game_mngr.npc_manager, 'mark_npc_dirty')):
                        await game_mngr.npc_manager.mark_npc_dirty(guild_id, npc_id)
                    update_successful = True
                log_value = str(processed_value)


            elif attribute in ["location_id", "faction_id", "archetype", "role"]:
                if not hasattr(npc, attribute):
                    await interaction.followup.send(f"**Мастер:** У NPC нет атрибута '{attribute}'.", ephemeral=True)
                    return

                original_value_str = str(getattr(npc, attribute, "N/A"))
                processed_value = value if value.lower() not in ["none", "null", ""] else None

                if attribute == "location_id" and processed_value is not None:
                    if not hasattr(game_mngr, 'location_manager') or not game_mngr.location_manager or \
                       not await game_mngr.location_manager.get_location_instance(guild_id, processed_value): # Add await
                        await interaction.followup.send(f"**Мастер:** Локация с ID '{processed_value}' не найдена.", ephemeral=True)
                        return

                if hasattr(game_mngr.npc_manager, 'update_npc_field') and callable(getattr(game_mngr.npc_manager, 'update_npc_field')):
                    update_successful = await game_mngr.npc_manager.update_npc_field(guild_id, npc_id, attribute, processed_value)
                else:
                    logging.warning(f"NpcManager for guild {guild_id} does not have a callable 'update_npc_field' method. Falling back to setattr for attribute {attribute}.")
                    setattr(npc, attribute, processed_value)
                    if hasattr(game_mngr.npc_manager, 'mark_npc_dirty') and callable(getattr(game_mngr.npc_manager, 'mark_npc_dirty')):
                        await game_mngr.npc_manager.mark_npc_dirty(guild_id, npc_id)
                    update_successful = True
                log_value = str(processed_value)
            else:
                await interaction.followup.send(f"**Мастер:** Атрибут '{attribute}' не поддерживается.", ephemeral=True)
                return

            if update_successful:
                if attribute.startswith("stats.") and hasattr(game_mngr.npc_manager, 'trigger_stats_recalculation') and callable(getattr(game_mngr.npc_manager, 'trigger_stats_recalculation')):
                    await game_mngr.npc_manager.trigger_stats_recalculation(guild_id, npc_id)

                log_details = {
                    "npc_id": npc_id, "npc_name": npc_name_for_log,
                    "attribute_changed": attribute, "old_value": original_value_str,
                    "new_value": log_value, "gm_user_id": str(interaction.user.id),
                    "gm_user_name": interaction.user.name
                }
                if game_mngr.game_log_manager and hasattr(game_mngr.game_log_manager, 'log_event') and callable(getattr(game_mngr.game_log_manager, 'log_event')):
                    await game_mngr.game_log_manager.log_event(guild_id=guild_id, event_type="gm_npc_edit", details=log_details)
                await interaction.followup.send(f"**Мастер:** NPC '{npc_name_for_log}' (`{npc_id}`) обновлен. '{attribute}': '{original_value_str}' -> '{log_value}'.", ephemeral=True)
            else:
                await interaction.followup.send(f"**Мастер:** Не удалось обновить '{attribute}' для NPC '{npc_name_for_log}'.", ephemeral=True)
        except Exception as e:
            logging.error(f"Error editing NPC {npc_id}: {e}", exc_info=True)
            await interaction.followup.send(f"**Мастер:** Ошибка редактирования NPC: {e}", ephemeral=True)

    @app_commands.command(name="master_edit_character", description="ГМ: Редактировать атрибут персонажа.")
    @app_commands.describe(character_id="ID персонажа/Discord ID.", attribute="Атрибут (name_i18n.en, stats.hp, level, etc.).", value="Новое значение.")
    @is_master_role()
    async def cmd_master_edit_character(self, interaction: Interaction, character_id: str, attribute: str, value: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        gid = str(interaction.guild_id)
        gm: Optional["GameManager"] = self.bot.game_manager
        if not gm or not hasattr(gm, 'character_manager') or not gm.character_manager or \
           not hasattr(gm, 'game_log_manager') or not gm.game_log_manager or \
           not hasattr(gm, 'location_manager') or not gm.location_manager:
            await interaction.followup.send("**Мастер:** Необходимые менеджеры недоступны.", ephemeral=True)
            return

        char = None
        if gm.character_manager: # Redundant check, but good for type safety if gm could be None earlier
            char_by_discord = await gm.character_manager.get_character_by_discord_id(gid, int(character_id)) if character_id.isdigit() else None
            char_by_id = await gm.character_manager.get_character(gid, character_id)
            char = char_by_discord or char_by_id

        if not char:
            await interaction.followup.send(f"**Мастер:** Персонаж '{character_id}' не найден.", ephemeral=True)
            return

        try:
            orig_val_str="N/A"; processed_val: Any = value; lang=str(interaction.locale or "en")

            char_id_for_log = getattr(char, "id", "UNKNOWN_ID")
            char_name_i18n_for_log = getattr(char, "name_i18n", {})
            char_name_for_log_attr = getattr(char, "name", char_id_for_log)

            char_name_log = char_name_i18n_for_log.get(lang, char_name_i18n_for_log.get("en",char_id_for_log)) if isinstance(char_name_i18n_for_log, dict) else char_name_for_log_attr
            update_success = False

            if attribute.startswith("name_i18n."):
                parts=attribute.split(".",1); field,code=parts[0],parts[1]
                i18n_d=getattr(char,field,{}); i18n_d=i18n_d if isinstance(i18n_d,dict) else {}
                orig_val_str=str(i18n_d.get(code,"N/A"))
                i18n_d[code]=value
                if code != 'en' and 'en' not in i18n_d and value.strip(): i18n_d['en'] = value
                if hasattr(gm.character_manager, 'save_character_field') and callable(getattr(gm.character_manager, 'save_character_field')):
                    update_success = await gm.character_manager.save_character_field(gid, char_id_for_log, field, i18n_d)
                else:
                    logging.warning(f"CharacterManager for guild {gid} does not have a callable 'save_character_field' method. Falling back to setattr for {field}.")
                    setattr(char, field, i18n_d)
                    update_success = True
                processed_val = i18n_d
            elif attribute.startswith("stats.") or attribute in ["level","experience","unspent_xp","hp","max_health","is_alive","gold"]:
                stat_key_for_update = attribute.split(".",1)[1] if attribute.startswith("stats.") else attribute
                current_stats_dict = getattr(char, 'stats', {}) if isinstance(getattr(char, 'stats', {}), dict) else {}
                _orig_val_for_type = current_stats_dict.get(stat_key_for_update) if attribute.startswith("stats.") else getattr(char,attribute,None)
                orig_val_str=str(_orig_val_for_type) if _orig_val_for_type is not None else "N/A"

                if _orig_val_for_type is not None and not isinstance(_orig_val_for_type,str):
                    try: processed_val = type(_orig_val_for_type)(value)
                    except ValueError: await interaction.followup.send(f"**Мастер:** Неверный тип для '{attribute}'. Ожидался {type(_orig_val_for_type).__name__}.",ephemeral=True); return
                elif attribute in ["level","experience","unspent_xp","gold"]:
                    try: processed_val = int(value)
                    except ValueError: await interaction.followup.send(f"**Мастер:** Неверный тип для '{attribute}'. Ожидается целое.",ephemeral=True); return
                elif attribute in ["hp","max_health"]:
                    try: processed_val = float(value)
                    except ValueError: await interaction.followup.send(f"**Мастер:** Неверный тип для '{attribute}'. Ожидается число.",ephemeral=True); return
                elif attribute=="is_alive":
                    processed_val = True if value.lower() in ["true","1","yes"] else (False if value.lower() in ["false","0","no"] else "INVALID_BOOL")
                    if processed_val == "INVALID_BOOL": await interaction.followup.send("**Мастер:** Неверное значение для 'is_alive'. True/False.",ephemeral=True); return

                if hasattr(gm.character_manager, 'update_character_stats') and callable(getattr(gm.character_manager, 'update_character_stats')):
                    update_success = await gm.character_manager.update_character_stats(gid, char_id_for_log, {stat_key_for_update:processed_val})
                else:
                    logging.warning(f"CharacterManager for guild {gid} does not have a callable 'update_character_stats' method. Falling back to direct modification.")
                    if attribute.startswith("stats."):
                        current_stats_dict[stat_key_for_update] = processed_val
                        setattr(char, 'stats', current_stats_dict)
                    else:
                        setattr(char, stat_key_for_update, processed_val)
                    update_success = True
            elif attribute == "character_class":
                orig_val_str = str(getattr(char, "character_class", "N/A"))
                processed_val = value
                if hasattr(gm.character_manager, 'save_character_field') and callable(getattr(gm.character_manager, 'save_character_field')):
                    update_success = await gm.character_manager.save_character_field(gid, char_id_for_log, "character_class", processed_val)
                else:
                    logging.warning(f"CharacterManager for guild {gid} does not have a callable 'save_character_field' method. Falling back to setattr for character_class.")
                    setattr(char, "character_class", processed_val)
                    update_success = True
                if update_success and hasattr(gm.character_manager, "trigger_stats_recalculation") and callable(getattr(gm.character_manager, "trigger_stats_recalculation")):
                    await gm.character_manager.trigger_stats_recalculation(gid, char_id_for_log)
            elif attribute == "selected_language":
                orig_val_str = str(getattr(char, "selected_language", "N/A"))
                processed_val = value
                if hasattr(gm.character_manager, 'save_character_field') and callable(getattr(gm.character_manager, 'save_character_field')):
                    update_success = await gm.character_manager.save_character_field(gid, char_id_for_log, "selected_language", processed_val)
                else:
                    logging.warning(f"CharacterManager for guild {gid} does not have a callable 'save_character_field' method. Falling back to setattr for selected_language.")
                    setattr(char, "selected_language", processed_val)
                    update_success = True
            elif attribute=="location_id":
                orig_val_str=str(getattr(char, 'location_id', "N/A")) # No await here, direct attribute access
                processed_val=value if value.lower() not in ["none", "null", ""] else None
                if hasattr(gm.character_manager, 'update_character_location') and callable(getattr(gm.character_manager, 'update_character_location')):
                    update_success = await gm.character_manager.update_character_location(char_id_for_log, processed_val, gid)
                else:
                    logging.warning(f"CharacterManager for guild {gid} does not have a callable 'update_character_location' method. Falling back to setattr for location_id.")
                    setattr(char, "location_id", processed_val) # No await here
                    update_success = True
            else:
                await interaction.followup.send(f"**Мастер:** Атрибут '{attribute}' не поддерживается.",ephemeral=True); return

            if update_success:
                char_discord_id = getattr(char, 'discord_user_id', None)
                log_d={"char_id":char_id_for_log,"char_name":char_name_log,"discord_id":str(char_discord_id) if char_discord_id else None,"attr":attribute,"old":orig_val_str,"new":str(processed_val),"gm_id":str(interaction.user.id),"gm_name":interaction.user.name}
                if gm.game_log_manager and hasattr(gm.game_log_manager, 'log_event') and callable(getattr(gm.game_log_manager, 'log_event')):
                    await gm.game_log_manager.log_event(gid,"gm_edit_character",details=log_d)
                await interaction.followup.send(f"**Мастер:** Персонаж '{char_name_log}' (`{char_id_for_log}`) обновлен: '{attribute}': '{orig_val_str}' -> '{str(processed_val)}'.",ephemeral=True)
            else:
                await interaction.followup.send(f"**Мастер:** Не удалось обновить '{attribute}' для '{char_name_log}'.", ephemeral=True)
        except Exception as e:
            logging.exception(f"Error editing character {character_id} in guild {gid}")
            await interaction.followup.send(f"**Мастер:** Ошибка редактирования персонажа: {e}",ephemeral=True)

    @app_commands.command(name="master_edit_item", description="ГМ: Редактировать атрибут экземпляра предмета.")
    @app_commands.describe(item_instance_id="ID экземпляра.", attribute="Атрибут (owner_id, quantity, state_variables.key).", value="Новое значение.")
    @is_master_role()
    async def cmd_master_edit_item(self, interaction: Interaction, item_instance_id: str, attribute: str, value: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        gid = str(interaction.guild_id)
        gm: Optional["GameManager"] = self.bot.game_manager
        if not gm or not hasattr(gm, 'item_manager') or not gm.item_manager or \
           not hasattr(gm, 'game_log_manager') or not gm.game_log_manager:
            await interaction.followup.send("**Мастер:** ItemManager/GameLogManager недоступен.", ephemeral=True)
            return

        item = await gm.item_manager.get_item_instance(gid, item_instance_id)

        if not item:
            await interaction.followup.send(f"**Мастер:** Предмет '{item_instance_id}' не найден.", ephemeral=True)
            return
        try:
            orig_val_str, payload, proc_val = "N/A", {}, value
            lang = str(interaction.locale or "en")
            item_tpl_name = getattr(item, 'template_id', item_instance_id)

            item_template_from_manager = None
            if hasattr(item, 'template_id') and hasattr(gm.item_manager, 'get_item_template') and callable(getattr(gm.item_manager, 'get_item_template')) :
                item_template_from_manager = await gm.item_manager.get_item_template(gid, getattr(item, 'template_id', ''))

            if item_template_from_manager and isinstance(item_template_from_manager, dict):
                 item_tpl_name_i18n = item_template_from_manager.get("name_i18n",{})
                 if isinstance(item_tpl_name_i18n, dict):
                     item_tpl_name=item_tpl_name_i18n.get(lang,item_tpl_name_i18n.get("en",getattr(item, 'template_id', item_instance_id)))

            if attribute.startswith("state_variables."):
                current_state_vars = getattr(item, 'state_variables', {})
                if not isinstance(current_state_vars,dict): current_state_vars={}
                key=attribute.split(".",1)[1]; orig_val=current_state_vars.get(key); orig_val_str=str(orig_val) if orig_val is not None else "N/A"
                if orig_val is not None:
                    try: proc_val = type(orig_val)(value)
                    except (ValueError, TypeError): proc_val = value
                else: # Infer type if key doesn't exist or value is None
                    try: proc_val = int(value)
                    except ValueError:
                        try: proc_val = float(value)
                        except ValueError:
                             if value.lower() == 'true': proc_val = True
                             elif value.lower() == 'false': proc_val = False
                             else: proc_val = value
                current_state_vars[key]=proc_val; payload["state_variables"]=current_state_vars
            elif attribute=="quantity":
                orig_val_str=str(getattr(item, 'quantity', "N/A"))
                try: proc_val=float(value)
                except ValueError: await interaction.followup.send("**Мастер:** Количество должно быть числом.",ephemeral=True); return
                if proc_val<=0: await interaction.followup.send("**Мастер:** Кол-во > 0.",ephemeral=True); return
                payload[attribute]=proc_val
            elif attribute in ["owner_id","owner_type","location_id"]:
                orig_val_str=str(getattr(item,attribute,"N/A")); proc_val=value if value.lower()not in ["none", "null", ""] else None; payload[attribute]=proc_val
                item_owner_type = getattr(item, 'owner_type', None)
                if attribute=="owner_id" and proc_val is not None: # If setting owner_id, clear location_id
                    payload["location_id"]=None
                    if not payload.get("owner_type") and not item_owner_type: # And ensure owner_type is set
                        await interaction.followup.send("**Мастер:** 'owner_type' (character, npc) обязателен при 'owner_id'.",ephemeral=True); return
                elif attribute=="owner_id" and proc_val is None: # If clearing owner_id, also clear owner_type
                    payload["owner_type"] = None
                elif attribute=="location_id" and proc_val is not None: # If setting location_id, clear owner
                    payload.update({"owner_id":None,"owner_type":None})
            else:
                await interaction.followup.send(f"**Мастер:** Атрибут '{attribute}' не поддерживается.",ephemeral=True); return

            if not payload:
                await interaction.followup.send(f"**Мастер:** Нечего обновлять для '{attribute}'.",ephemeral=True); return

            update_item_success = False
            if hasattr(gm.item_manager, 'update_item_instance') and callable(getattr(gm.item_manager, 'update_item_instance')):
                update_item_success = await gm.item_manager.update_item_instance(gid,item_instance_id,payload)

            if update_item_success:
                log_d={"item_id":item_instance_id,"item_name":item_tpl_name,"attr":attribute,"old":orig_val_str,"new":str(proc_val),"gm_id":str(interaction.user.id),"gm_name":interaction.user.name}
                if gm.game_log_manager and hasattr(gm.game_log_manager, 'log_event') and callable(getattr(gm.game_log_manager, 'log_event')):
                     await gm.game_log_manager.log_event(gid,"gm_edit_item",details=log_d)
                await interaction.followup.send(f"**Мастер:** Предмет '{item_tpl_name}' (`{item_instance_id}`) обновлен: '{attribute}': '{orig_val_str}' -> '{str(proc_val)}'.",ephemeral=True)
            else:
                await interaction.followup.send(f"**Мастер:** Ошибка обновления '{item_instance_id}'.",ephemeral=True)
        except Exception as e:
            logging.error(f"Error editing item {item_instance_id}: {e}", exc_info=True)
            await interaction.followup.send(f"**Мастер:** Ошибка: {e}",ephemeral=True)

    @app_commands.command(name="master_create_item", description="ГМ: Создать новый экземпляр предмета.")
    @app_commands.describe(template_id="ID шаблона.", target_id="Опц: ID владельца/локации.", target_type="Опц: Тип цели ('character', 'npc', 'location').", quantity="Опц: Количество (default 1).")
    @is_master_role()
    async def cmd_master_create_item(self, interaction: Interaction, template_id: str, target_id: Optional[str]=None, target_type: Optional[str]=None, quantity: Optional[float]=1.0):
        await interaction.response.defer(ephemeral=True,thinking=True)
        gid = str(interaction.guild_id)
        gm: Optional["GameManager"] = self.bot.game_manager
        if not gm or not all(hasattr(gm, mngr_name) and getattr(gm, mngr_name) is not None for mngr_name in ['item_manager', 'game_log_manager', 'character_manager', 'npc_manager', 'location_manager']):
            await interaction.followup.send("**Мастер:** Один из менеджеров недоступен.",ephemeral=True); return

        qty=quantity if quantity is not None and quantity > 0 else 1.0
        item_manager = cast("ItemManager", gm.item_manager) # Cast after check
        character_manager = cast("CharacterManager", gm.character_manager)
        npc_manager = cast("NpcManager", gm.npc_manager)
        location_manager = cast("LocationManager", gm.location_manager)
        game_log_manager = cast("GameLogManager", gm.game_log_manager)


        item_tpl = await item_manager.get_item_template(gid, template_id)
        if not item_tpl or not isinstance(item_tpl, dict):
            await interaction.followup.send(f"**Мастер:** Шаблон '{template_id}' не найден или некорректен.",ephemeral=True); return

        tpl_name_log=item_tpl.get("name_i18n",{}).get("en",template_id); own_id,own_type,loc_id=None,None,None
        if target_id:
            if not target_type: await interaction.followup.send("**Мастер:** 'target_type' обязателен при 'target_id'.",ephemeral=True); return
            tt=target_type.lower()
            if tt in ["character","player"]:
                char_obj = await character_manager.get_character_by_discord_id(gid,int(target_id)) if target_id.isdigit() else await character_manager.get_character(gid,target_id)
                if not char_obj: await interaction.followup.send(f"**Мастер:** Персонаж '{target_id}' не найден.",ephemeral=True); return
                own_id,own_type=getattr(char_obj, 'id', None),"Character"
            elif tt=="npc":
                npc_obj = await npc_manager.get_npc(gid,target_id)
                if not npc_obj: await interaction.followup.send(f"**Мастер:** NPC '{target_id}' не найден.",ephemeral=True); return
                own_id,own_type=getattr(npc_obj, 'id', None),"NPC"
            elif tt=="location":
                loc_obj = await location_manager.get_location_instance(gid, target_id)
                if not loc_obj: await interaction.followup.send(f"**Мастер:** Локация '{target_id}' не найдена.",ephemeral=True); return
                loc_id=getattr(loc_obj, 'id', None)
            else: await interaction.followup.send("**Мастер:** Неверный 'target_type'. Допустимые: character, player, npc, location.",ephemeral=True); return
        try:
            new_item_instance = await item_manager.create_item_instance(
                    guild_id=gid, template_id=template_id, owner_id=own_id,
                    owner_type=own_type, location_id=loc_id, quantity=qty
            )
            if new_item_instance and hasattr(new_item_instance, 'id'):
                log_d={"item_id":new_item_instance.id,"tpl_id":template_id,"tpl_name":tpl_name_log,"qty":qty,"owner":own_id,"owner_t":own_type,"loc":loc_id,"gm_id":str(interaction.user.id),"gm_name":interaction.user.name}
                if hasattr(game_log_manager, 'log_event') and callable(getattr(game_log_manager, 'log_event')) :
                    await game_log_manager.log_event(gid,"gm_create_item",details=log_d)
                msg=f"**Мастер:** Предмет '{tpl_name_log}' (ID: {new_item_instance.id}) x{qty} создан."
                if own_id: msg+=f" Владелец: {own_type} {own_id}."
                elif loc_id: msg+=f" В локации {loc_id}."
                else: msg += " (без владельца и не в локации)."
                await interaction.followup.send(msg,ephemeral=True)
            else: await interaction.followup.send(f"**Мастер:** Ошибка создания '{template_id}'.",ephemeral=True)
        except Exception as e:
            logging.error(f"Error creating item {template_id}: {e}", exc_info=True)
            await interaction.followup.send(f"**Мастер:** Ошибка: {e}",ephemeral=True)

    @app_commands.command(name="master_launch_event", description="ГМ: Запустить событие по шаблону.")
    @app_commands.describe(template_id="ID шаблона.",location_id="Опц: ID локации.",channel_id="Опц: ID канала.",player_ids_json="Опц: JSON массив ID игроков.")
    @is_master_role()
    async def cmd_master_launch_event(self, interaction: Interaction, template_id:str, location_id:Optional[str]=None, channel_id:Optional[str]=None, player_ids_json:Optional[str]=None):
        await interaction.response.defer(ephemeral=True,thinking=True)
        gid = str(interaction.guild_id)
        gm: Optional["GameManager"] = self.bot.game_manager
        if not gm or not hasattr(gm, 'event_manager') or not gm.event_manager or \
           not hasattr(gm, 'game_log_manager') or not gm.game_log_manager:
            await interaction.followup.send("**Мастер:** EventManager/GameLogManager недоступен.",ephemeral=True); return

        event_manager = cast("EventManager", gm.event_manager)
        game_log_manager = cast("GameLogManager", gm.game_log_manager)

        evt_tpl = await event_manager.get_event_template(gid, template_id)

        if not evt_tpl or not isinstance(evt_tpl, dict):
            await interaction.followup.send(f"**Мастер:** Шаблон '{template_id}' не найден или некорректен.",ephemeral=True); return

        tpl_name_log=evt_tpl.get("name",template_id); p_ids:Optional[List[str]]=None
        if player_ids_json:
            try: p_ids=json.loads(player_ids_json)
            except json.JSONDecodeError: await interaction.followup.send("**Мастер:** Ошибка JSON 'player_ids_json'.",ephemeral=True); return
            if not isinstance(p_ids,list) or not all(isinstance(p,str) for p in p_ids):
                await interaction.followup.send("**Мастер:** 'player_ids_json' должен быть массивом строк.",ephemeral=True); return

        p_chan_id_int:Optional[int]=None
        if channel_id:
            try: p_chan_id_int=int(channel_id)
            except ValueError: await interaction.followup.send("**Мастер:** 'channel_id' должен быть числом.",ephemeral=True); return
        try:
            created_evt = await event_manager.create_event_from_template(
                    guild_id=gid, template_id=template_id, target_location_id=location_id,
                    involved_player_ids=p_ids, channel_id_override=p_chan_id_int
            )
            if created_evt and hasattr(created_evt, 'id'):
                log_d={"evt_id":created_evt.id,"tpl_id":template_id,"tpl_name":tpl_name_log,"loc":location_id,"chan":p_chan_id_int,"p_ids":p_ids,"gm_id":str(interaction.user.id),"gm_name":interaction.user.name}
                if hasattr(game_log_manager, 'log_event') and callable(getattr(game_log_manager, 'log_event')):
                    await game_log_manager.log_event(gid,"gm_launch_event",details=log_d)
                evt_n=getattr(created_evt,'name',tpl_name_log)
                await interaction.followup.send(f"**Мастер:** Событие '{evt_n}' (ID:{created_evt.id}) запущено из '{template_id}'.",ephemeral=True)
            else: await interaction.followup.send(f"**Мастер:** Ошибка запуска '{template_id}'.",ephemeral=True)
        except Exception as e:
            logging.error(f"Error launching event {template_id}: {e}", exc_info=True)
            await interaction.followup.send(f"**Мастер:** Ошибка: {e}",ephemeral=True)

    @app_commands.command(name="master_set_rule", description="ГМ: Установить значение для правила игры.")
    @app_commands.describe(rule_key="Путь к правилу (e.g., economy_rules.multiplier).",value_json="JSON значение.")
    @is_master_role()
    async def cmd_master_set_rule(self, interaction: Interaction, rule_key: str, value_json: str):
        await interaction.response.defer(ephemeral=True,thinking=True)
        gid = str(interaction.guild_id)
        gm: Optional["GameManager"] = self.bot.game_manager
        db_service = getattr(self.bot, "db_service", None)

        if not db_service or not hasattr(db_service, 'adapter') or not db_service.adapter:
            await interaction.followup.send("**Мастер:** DBService недоступен.",ephemeral=True); return
        if not gm or not hasattr(gm, 'game_log_manager') or not gm.game_log_manager:
            await interaction.followup.send("**Мастер:** GameLogManager недоступен.",ephemeral=True); return

        game_log_manager = cast("GameLogManager", gm.game_log_manager)

        try:
            cfg_dict: Optional[Dict[str, Any]] = None; new_cfg = False
            rule_engine_instance: Optional["RuleEngine"] = getattr(gm, 'rule_engine', None)

            if rule_engine_instance:
                if hasattr(rule_engine_instance, 'get_raw_rules_config_dict_for_guild') and callable(getattr(rule_engine_instance, 'get_raw_rules_config_dict_for_guild')):
                    cfg_dict = await rule_engine_instance.get_raw_rules_config_dict_for_guild(gid)

                if not cfg_dict:
                    if hasattr(rule_engine_instance, 'get_default_rules_config_data_model') and callable(getattr(rule_engine_instance, 'get_default_rules_config_data_model')):
                         cfg_model_instance = rule_engine_instance.get_default_rules_config_data_model()
                         if hasattr(cfg_model_instance, 'model_dump') and callable(cfg_model_instance.model_dump):
                            cfg_dict = cfg_model_instance.model_dump() # No args for Pydantic V2
                         new_cfg = True
                    else:
                        logging.warning(f"RuleEngine for guild {gid} missing 'get_default_rules_config_data_model'. Falling back to default RuleConfigData.")
                        from bot.api.schemas.rule_config_schemas import RuleConfigData
                        cfg_dict = RuleConfigData().model_dump() # No args for Pydantic V2
                        new_cfg = True
            elif db_service.adapter: # This path might need review for RuleEngine integration
                row = await db_service.adapter.fetchone("SELECT config_data FROM rules_config WHERE guild_id=$1",(gid,))
                if row and row['config_data']:
                    cfg_dict=row['config_data'] if isinstance(row['config_data'],dict) else json.loads(str(row['config_data']))
                else:
                    from bot.api.schemas.rule_config_schemas import RuleConfigData
                    new_cfg=True; cfg_dict=RuleConfigData().model_dump() # No args for Pydantic V2

            if cfg_dict is None: # Should not happen if the above logic correctly initializes cfg_dict
                await interaction.followup.send("**Мастер:** Не удалось получить/создать конфигурацию правил.",ephemeral=True); return

            try: new_val_parsed=json.loads(value_json)
            except json.JSONDecodeError: await interaction.followup.send(f"**Мастер:** Ошибка JSON: `{value_json}`.",ephemeral=True); return

            keys,curr_lvl,orig_val=rule_key.split('.'),cfg_dict,None
            for i,k_part in enumerate(keys[:-1]):
                if not isinstance(curr_lvl,dict) or k_part not in curr_lvl: # curr_lvl could be None if path is wrong
                    await interaction.followup.send(f"**Мастер:** Путь '{rule_key}', ключ '{k_part}' не найден.",ephemeral=True); return
                curr_lvl=curr_lvl[k_part]

            f_key=keys[-1]
            if not isinstance(curr_lvl,dict): # curr_lvl could be None
                await interaction.followup.send(f"**Мастер:** Путь '{rule_key}', родитель для '{f_key}' не словарь.",ephemeral=True); return

            processed_val_for_dict = new_val_parsed
            if f_key in curr_lvl and curr_lvl[f_key] is not None:
                orig_val=curr_lvl[f_key]; target_type=type(orig_val)
                try:
                    if target_type == bool and isinstance(new_val_parsed, str):
                        processed_val_for_dict = new_val_parsed.lower() == 'true'
                    else:
                        processed_val_for_dict = target_type(new_val_parsed)
                except (ValueError,TypeError) as e:
                    await interaction.followup.send(f"**Мастер:** Ошибка типа для '{f_key}'. Ожидался {target_type.__name__}, получен '{value_json}'. Ошибка: {e}",ephemeral=True); return

            curr_lvl[f_key]=processed_val_for_dict
            orig_val_str=str(orig_val) if orig_val is not None else "N/A (новый ключ)"

            save_successful = False
            if rule_engine_instance and hasattr(rule_engine_instance, 'save_rules_config_for_guild_from_dict') and callable(getattr(rule_engine_instance, 'save_rules_config_for_guild_from_dict')):
                save_successful = await rule_engine_instance.save_rules_config_for_guild_from_dict(gid, cfg_dict)
            elif db_service.adapter: # Fallback if RuleEngine method not available or RE itself is None
                logging.warning(f"RuleEngine method 'save_rules_config_for_guild_from_dict' not available or RE is None for guild {gid}. Falling back to direct DB write.")
                if new_cfg: await db_service.adapter.execute("INSERT INTO rules_config (guild_id,config_data) VALUES ($1,$2)",(gid,json.dumps(cfg_dict)))
                else: await db_service.adapter.execute("UPDATE rules_config SET config_data=$1 WHERE guild_id=$2",(json.dumps(cfg_dict),gid))
                save_successful = True

            if not save_successful: # This means neither RE save nor DB direct save worked
                await interaction.followup.send("**Мастер:** Не удалось сохранить конфигурацию правил.",ephemeral=True); return


            if rule_engine_instance and hasattr(rule_engine_instance,'load_rules_config_for_guild') and callable(getattr(rule_engine_instance,'load_rules_config_for_guild')):
                try:
                    await rule_engine_instance.load_rules_config_for_guild(gid)
                except Exception as e_rl: logging.exception(f"Error reloading RuleEngine for {gid} after setting rule {rule_key}")

            log_d={"gid":gid,"key":rule_key,"old":orig_val_str,"new_json":value_json,"new_val_processed":processed_val_for_dict,"gm_id":str(interaction.user.id),"gm_name":interaction.user.name}
            if hasattr(game_log_manager, 'log_event') and callable(getattr(game_log_manager, 'log_event')):
                await game_log_manager.log_event(gid,"gm_set_rule",details=log_d)
            await interaction.followup.send(f"**Мастер:** Правило '{rule_key}' установлено на '{json.dumps(processed_val_for_dict)}'.",ephemeral=True)
        except Exception as e:
            logging.exception(f"Error setting rule {rule_key} for guild {gid}")
            await interaction.followup.send(f"**Мастер:** Ошибка установки правила: {e}",ephemeral=True)

    @app_commands.command(name="run_simulation", description="ГМ: Запустить симуляцию (бой, квест, последствия).")
    @app_commands.choices(simulation_type=[app_commands.Choice(name="Battle",value="battle"), app_commands.Choice(name="Quest",value="quest"), app_commands.Choice(name="Action Consequence",value="action_consequence")])
    @app_commands.describe(simulation_type="Тип симуляции.", params_json="JSON параметры.")
    @is_master_role()
    async def cmd_run_simulation(self, interaction: Interaction, simulation_type: app_commands.Choice[str], params_json: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        gid = str(interaction.guild_id)
        gm: Optional["GameManager"] = self.bot.game_manager
        if not gm: await interaction.followup.send("**Мастер:** GameManager недоступен.", ephemeral=True); return

        from bot.game.services.report_formatter import SimpleReportFormatter

        req_mgrs = ['character_manager','npc_manager','rule_engine','game_log_manager','item_manager','event_manager','combat_manager','relationship_manager','location_manager']
        if simulation_type.value=="quest" and (not hasattr(gm,'quest_manager') or not gm.quest_manager):
            logging.warning(f"QuestManager missing for quest simulation in guild {gid}.")

        for mgr_name in req_mgrs:
            if not (simulation_type.value=="quest" and mgr_name=='quest_manager'): # Don't check quest_manager if not a quest sim
                 if not hasattr(gm, mgr_name) or getattr(gm, mgr_name) is None:
                    await interaction.followup.send(f"**Мастер:** Менеджер '{mgr_name}' недоступен.", ephemeral=True); return

        # Ensure managers are not None before casting/using
        character_manager = cast("CharacterManager", gm.character_manager)
        npc_manager = cast("NpcManager", gm.npc_manager)
        rule_engine = cast("RuleEngine", gm.rule_engine)
        item_manager = cast("ItemManager", gm.item_manager)
        event_manager = cast("EventManager", gm.event_manager)
        combat_manager = cast("CombatManager", gm.combat_manager)
        relationship_manager = cast("RelationshipManager", gm.relationship_manager)
        game_log_manager = cast("GameLogManager", gm.game_log_manager)
        quest_manager = cast("QuestManager", getattr(gm, 'quest_manager', None)) # Optional, checked below

        import uuid
        from bot.game.simulation import BattleSimulator,QuestSimulator,ActionConsequenceModeler
        try: params = json.loads(params_json)
        except json.JSONDecodeError: await interaction.followup.send("**Мастер:** Ошибка JSON в параметрах.", ephemeral=True); return

        report, fmt, rep_id, lang = None, SimpleReportFormatter(gm,gid), str(uuid.uuid4()), str(interaction.locale or "en")
        fmtd_report = ""
        try:
            if simulation_type.value=="battle":
                sim=BattleSimulator(gid,character_manager,npc_manager,combat_manager,rule_engine,item_manager)
                report=await sim.simulate_full_battle(params.get('participants_setup',[]),params.get('rules_config_override_data'),params.get('max_rounds',50))
                if report: fmtd_report=fmt.format_battle_report(report,lang)
            elif simulation_type.value=="quest":
                if not quest_manager:
                    await interaction.followup.send("**Мастер:** QuestManager недоступен для симуляции квеста.",ephemeral=True); return
                qdefs = {}
                if hasattr(quest_manager, 'get_all_quest_definitions') and callable(quest_manager.get_all_quest_definitions): # type: ignore[attr-defined]
                     qdefs = await quest_manager.get_all_quest_definitions(gid) # type: ignore[attr-defined]
                if not qdefs and not params.get('quest_definitions_override'):
                    await interaction.followup.send("**Мастер:** Определения квестов не найдены.",ephemeral=True); return
                sim=QuestSimulator(gid,character_manager,event_manager,rule_engine,params.get('quest_definitions_override',qdefs or {}))
                report=await sim.simulate_full_quest(params.get('quest_id',''),params.get('character_ids',[]),params.get('rules_config_override_data'),params.get('max_stages',20))
                if report and isinstance(report, dict): fmtd_report=fmt.format_quest_report(report,lang)
            elif simulation_type.value=="action_consequence":
                sim=ActionConsequenceModeler(gid,character_manager,npc_manager,rule_engine,relationship_manager,event_manager)
                report_data_raw=await sim.analyze_action_consequences(params.get('action_description',{}),params.get('actor_id',''),params.get('actor_type',''),params.get('target_id'),params.get('target_type'),params.get('rules_config_override_data')) # Add await
                report = report_data_raw
                if report_data_raw:
                    data_for_formatter = report_data_raw if isinstance(report_data_raw, list) else [report_data_raw]
                    fmtd_report=fmt.format_action_consequence_report(data_for_formatter ,lang)
            else: await interaction.followup.send(f"**Мастер:** Неизвестный тип симуляции '{simulation_type.value}'.",ephemeral=True); return

            if report is not None:
                if hasattr(game_log_manager, 'log_event') and callable(getattr(game_log_manager, 'log_event')):
                    await game_log_manager.log_event(gid,"gm_simulation_report",{"report_id":rep_id,"type":simulation_type.value,"params_json_snapshot":params_json,"report_data":report})
                msg=f"Симуляция '{simulation_type.name}' завершена. ID Отчета: `{rep_id}`\n\n{fmtd_report}"
                await interaction.followup.send(msg[:1950]+("..." if len(msg)>1950 else ""),ephemeral=True)
            else: await interaction.followup.send(f"**Мастер:** Симуляция '{simulation_type.name}' не дала результатов или произошла ошибка формирования отчета.",ephemeral=True)
        except Exception as e:
            logging.exception(f"Error during simulation {simulation_type.name} for guild {gid}")
            await interaction.followup.send(f"**Мастер:** Ошибка симуляции '{simulation_type.name}': {e}",ephemeral=True)

    @app_commands.command(name="view_simulation_report",description="ГМ: Просмотреть отчет симуляции.")
    @app_commands.describe(report_id="ID отчета.")
    @is_master_role()
    async def cmd_view_simulation_report(self, interaction: Interaction, report_id: str):
        await interaction.response.defer(ephemeral=True,thinking=True)
        gid = str(interaction.guild_id)
        gm: Optional["GameManager"] = self.bot.game_manager
        if not gm or not hasattr(gm, 'game_log_manager') or not gm.game_log_manager:
            await interaction.followup.send("**Мастер:** GameLogManager недоступен.",ephemeral=True); return

        game_log_manager = cast("GameLogManager", gm.game_log_manager)
        try:
            logs=await game_log_manager.get_logs_by_guild(gid,limit=500,event_type_filter="gm_simulation_report")
            entry_data:Optional[Dict[str,Any]]=None
            for log_row_dict in logs:
                details=log_row_dict.get('details')
                if isinstance(details,dict) and details.get('report_id')==report_id:
                    entry_data=details; break
            if entry_data and 'report_data' in entry_data and 'type' in entry_data:
                report_data,sim_type_from_log,lang=entry_data['report_data'],entry_data['type'],str(interaction.locale or "en")
                from bot.game.services.report_formatter import SimpleReportFormatter
                fmt=SimpleReportFormatter(gm,gid)
                if not isinstance(report_data, (dict, list)): # report_data can be a dict or list of dicts
                    await interaction.followup.send(f"**Мастер:** Ошибка: данные отчета '{report_id}' неверны.", ephemeral=True); return

                formatter_method_name = f"format_{sim_type_from_log}_report"
                fmtd_report = ""
                if hasattr(fmt, formatter_method_name) and callable(getattr(fmt, formatter_method_name)):
                    formatter_method = getattr(fmt, formatter_method_name)
                    if sim_type_from_log == "action_consequence" and not isinstance(report_data, list):
                        report_data = [report_data] # Ensure it's a list for this specific formatter
                    fmtd_report = formatter_method(report_data, lang)
                elif hasattr(fmt, "format_generic_report") and callable(getattr(fmt, "format_generic_report")): # Fallback for generic
                    fmtd_report = fmt.format_generic_report({"content": report_data, "title": f"Generic Report for {sim_type_from_log}"}, lang)
                else:
                    logging.warning(f"ReportFormatter missing specific method '{formatter_method_name}' and generic 'format_generic_report' for sim_type '{sim_type_from_log}'.")
                    fmtd_report = f"Error: No formatter found for report type '{sim_type_from_log}'. Raw data: {str(report_data)[:500]}"


                msg=f"**Отчет (ID: {report_id}, Тип: {sim_type_from_log})**:\n\n{fmtd_report}"
                await interaction.followup.send(msg[:1950]+("..." if len(msg)>1950 else ""),ephemeral=True)
            else: await interaction.followup.send(f"**Мастер:** Отчет ID '{report_id}' не найден.",ephemeral=True)
        except Exception as e:
            logging.error(f"Error viewing report {report_id}: {e}", exc_info=True)
            await interaction.followup.send(f"**Мастер:** Ошибка просмотра отчета: {e}",ephemeral=True)

    @app_commands.command(name="compare_reports",description="ГМ: Сравнить два отчета (концепт).")
    @app_commands.describe(report_id_1="ID первого отчета.",report_id_2="ID второго отчета.")
    @is_master_role()
    async def cmd_compare_reports(self, interaction:Interaction, report_id_1:str, report_id_2:str):
        await interaction.response.defer(ephemeral=True,thinking=True)
        await interaction.followup.send(f"**Мастер:** Сравнение '{report_id_1}' и '{report_id_2}'. Функция в разработке.",ephemeral=True)

    @app_commands.command(name="master_view_npcs", description="ГМ: Просмотреть NPC (фильтр по локации).")
    @app_commands.describe(location_id_filter="Опц: ID локации.")
    @is_master_role()
    async def cmd_master_view_npcs(self, interaction: Interaction, location_id_filter: Optional[str]=None):
        await interaction.response.defer(ephemeral=True,thinking=True)
        gid = str(interaction.guild_id)
        gm: Optional["GameManager"] = self.bot.game_manager
        lang = str(interaction.locale or "en")
        if not gm or not hasattr(gm, 'npc_manager') or not gm.npc_manager or \
           not hasattr(gm, 'location_manager') or not gm.location_manager:
            await interaction.followup.send("**Мастер:** NPC/Location Manager недоступен.",ephemeral=True); return

        npc_manager = cast("NpcManager", gm.npc_manager)
        location_manager = cast("LocationManager", gm.location_manager)

        npc_list_any: List[Any] = [] # Kept as List[Any] due to previous notes on model type variance
        header_str: str; loc = None

        if location_id_filter:
            loc = await location_manager.get_location_instance(gid, location_id_filter)

        if location_id_filter:
            if not loc: await interaction.followup.send(f"**Мастер:** Локация '{location_id_filter}' не найдена.",ephemeral=True); return
            loc_name_i18n = getattr(loc,"name_i18n",{})
            loc_name = loc_name_i18n.get(lang,loc_name_i18n.get("en",getattr(loc,"id","UNKNOWN_LOC_ID"))) if isinstance(loc_name_i18n, dict) else getattr(loc,"name",getattr(loc,"id","UNKNOWN_LOC_ID"))
            header_str = f"**NPC в локации '{loc_name}' (`{location_id_filter}`)**\n"
            npc_list_any = await npc_manager.get_npcs_in_location(gid, location_id_filter)
        else:
            header_str = "**Все NPC в гильдии**\n";
            npc_list_any = await npc_manager.get_all_npcs(gid)

        if not npc_list_any:
            await interaction.followup.send(f"**Мастер:** NPC не найдены {(f'в `{location_id_filter}`' if location_id_filter else 'в гильдии')}.",ephemeral=True); return

        content_lines:List[str]=[]
        for npc_item_any in npc_list_any:
            npc_name_i18n = getattr(npc_item_any,"name_i18n",{})
            npc_name = npc_name_i18n.get(lang,npc_name_i18n.get("en",getattr(npc_item_any,"id","N/A"))) if isinstance(npc_name_i18n, dict) else getattr(npc_item_any,"name",getattr(npc_item_any,"id","N/A"))

            loc_str="N/A"; loc_inst_for_npc = None
            npc_loc_id = getattr(npc_item_any, 'location_id', None)
            if npc_loc_id:
                loc_inst_for_npc = await location_manager.get_location_instance(gid,npc_loc_id)

            if npc_loc_id and loc_inst_for_npc:
                loc_n_i18n = getattr(loc_inst_for_npc,"name_i18n",{})
                loc_n=(loc_n_i18n.get(lang,loc_n_i18n.get("en",getattr(loc_inst_for_npc,"id","N/A"))) if isinstance(loc_n_i18n, dict) else getattr(loc_inst_for_npc,"name",getattr(loc_inst_for_npc,"id","N/A")))
                loc_str=f"{loc_n} (`{npc_loc_id}`)"
            elif npc_loc_id: loc_str=f"Unknown (`{npc_loc_id}`)"
            content_lines.append(f"- ID:`{getattr(npc_item_any,'id','N/A')}` Имя:**{npc_name}** Лок:{loc_str} HP:{getattr(npc_item_any,'hp','N/A')}/{getattr(npc_item_any,'max_health','N/A')}")

        msgs_to_send,current_msg_part=[],header_str
        for line_item in content_lines:
            if len(current_msg_part)+len(line_item)+1 > 1950:
                msgs_to_send.append(current_msg_part.strip()); current_msg_part=line_item
            else:
                if not current_msg_part.endswith("\n"): current_msg_part += "\n"
                current_msg_part+=line_item
        if current_msg_part.strip() and (current_msg_part.strip() != header_str.strip() or not content_lines):
             if current_msg_part.strip() != header_str.strip() or not msgs_to_send :
                msgs_to_send.append(current_msg_part.strip())
        if not msgs_to_send:
            await interaction.followup.send(header_str if header_str.strip() and not content_lines else "**Мастер:** Нечего отображать.",ephemeral=True)
            return
        for i,final_part_msg in enumerate(msgs_to_send):
            page_prefix = f"(Часть {i+1}/{len(msgs_to_send)})\n" if len(msgs_to_send) > 1 else ""
            await interaction.followup.send(f"{page_prefix}{final_part_msg}",ephemeral=True)

    @app_commands.command(name="master_view_log", description="ГМ: Просмотреть логи событий сервера.")
    @app_commands.describe(event_type_filter="Опц: Фильтр по типу события.", limit="Опц: Кол-во записей (1-200, default 50).")
    @is_master_role()
    async def cmd_master_view_log(self, interaction: Interaction, event_type_filter: Optional[str]=None, limit:app_commands.Range[int,1,200]=50): # type: ignore[assignment] # Range implies int
        await interaction.response.defer(ephemeral=True,thinking=True)
        guild_id_str = str(interaction.guild_id)
        game_mngr: Optional["GameManager"] = self.bot.game_manager
        if not game_mngr or not hasattr(game_mngr, 'game_log_manager') or not game_mngr.game_log_manager:
            await interaction.followup.send("**Мастер:** GameLogManager недоступен.",ephemeral=True); return

        game_log_manager = cast("GameLogManager", game_mngr.game_log_manager)

        try: from bot.game.services.report_formatter import ReportFormatter
        except ImportError: await interaction.followup.send("**Мастер:** ReportFormatter не найден.",ephemeral=True); return

        if not all(hasattr(game_mngr,mgr_name) and getattr(game_mngr,mgr_name) for mgr_name in ['character_manager','npc_manager','item_manager']):
            await interaction.followup.send("**Мастер:** Менеджеры для ReportFormatter недоступны.",ephemeral=True); return

        character_manager = cast("CharacterManager", game_mngr.character_manager)
        npc_manager = cast("NpcManager", game_mngr.npc_manager)
        item_manager = cast("ItemManager", game_mngr.item_manager)

        fmt=ReportFormatter(character_manager,npc_manager,item_manager)
        try:
            logs=await game_log_manager.get_logs_by_guild(guild_id_str,limit=(limit or 50),event_type_filter=event_type_filter)
            if not logs: await interaction.followup.send(f"**Мастер:** Логи не найдены (фильтр: '{event_type_filter or 'Нет'}').",ephemeral=True); return

            lang,log_lines=str(interaction.locale or "en"),[]
            from datetime import timezone
            for entry_dict in logs:
                ts = entry_dict.get('timestamp')
                ts_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z") if ts and hasattr(ts, 'astimezone') else 'N/A'
                et_str=str(entry_dict.get('event_type','N/A'))
                try:
                    desc=await fmt.format_story_log_entry(entry_dict,lang)
                    details_data,preview_str=entry_dict.get('details'),""
                    if isinstance(details_data,dict):
                        preview_items = list(details_data.items())[:2]
                        preview_str=f" (...{', '.join([f'{k}: {str(v)[:30]}' for k,v in preview_items])}...)"
                    log_lines.append(f"`{ts_str}` `[{et_str}]` {desc}{preview_str}")
                except Exception as e_fmt:
                    log_lines.append(f"`{ts_str}` `[{et_str}]` Ошибка форматирования лога ID {entry_dict.get('id', 'N/A')}: {e_fmt}")

            msgs_to_send_log,current_msg_part_log= [], ""
            header_log = f"**Игровой лог ({len(log_lines)} записей)**\n"
            current_msg_part_log = header_log
            for log_line_content in log_lines:
                if len(current_msg_part_log) + len(log_line_content) + 1 > 1950:
                    msgs_to_send_log.append(current_msg_part_log.strip()); current_msg_part_log = log_line_content
                else:
                    if not current_msg_part_log.endswith("\n"): current_msg_part_log += "\n"
                    current_msg_part_log += log_line_content

            if current_msg_part_log.strip() and (current_msg_part_log.strip() != header_log.strip() or not log_lines):
                 if current_msg_part_log.strip() != header_log.strip() or not msgs_to_send_log:
                    msgs_to_send_log.append(current_msg_part_log.strip())

            if not msgs_to_send_log:
                await interaction.followup.send(header_log if header_log.strip() and not log_lines else "**Мастер:** Нечего отображать.",ephemeral=True)
                return

            for i,final_log_part in enumerate(msgs_to_send_log):
                page_prefix_log = f"(Часть {i+1}/{len(msgs_to_send_log)})\n" if len(msgs_to_send_log) > 1 else ""
                await interaction.followup.send(f"{page_prefix_log}{final_log_part}",ephemeral=True)
        except Exception as e:
            logging.error(f"Error viewing logs: {e}", exc_info=True)
            await interaction.followup.send(f"**Мастер:** Ошибка просмотра логов: {e}",ephemeral=True)

    @app_commands.command(name="master_view_player_stats", description="ГМ: Просмотреть статы и информацию об игроке.")
    @app_commands.describe(character_id="ID персонажа или Discord ID игрока.")
    @is_master_role()
    async def cmd_master_view_player_stats(self, interaction: Interaction, character_id: str):
        await interaction.response.defer(ephemeral=True,thinking=True)
        guild_id_str = str(interaction.guild_id)
        game_mngr: Optional["GameManager"] = self.bot.game_manager
        if not game_mngr or not hasattr(game_mngr, 'character_manager') or not game_mngr.character_manager or \
           not hasattr(game_mngr, 'location_manager') or not game_mngr.location_manager:
            await interaction.followup.send("**Мастер:** Character/LocationManager недоступен.",ephemeral=True); return

        character_manager = cast("CharacterManager", game_mngr.character_manager)
        location_manager = cast("LocationManager", game_mngr.location_manager)

        char = None
        # Ensure character_manager is not None before calling methods on it
        char_by_discord = await character_manager.get_character_by_discord_id(guild_id_str, int(character_id)) if character_id.isdigit() else None
        char_by_id = await character_manager.get_character(guild_id_str, character_id)
        char = char_by_discord or char_by_id

        if not char:
            await interaction.followup.send(f"**Мастер:** Персонаж '{character_id}' не найден.",ephemeral=True); return

        lang = str(interaction.locale or "en")

        char_id_val = getattr(char, "id", "UNKNOWN_ID")
        char_name_i18n_val = getattr(char, "name_i18n", {})
        char_name_val = getattr(char, "name", char_id_val) # Fallback if name_i18n is missing
        char_discord_user_id_val = getattr(char, "discord_user_id", "N/A")
        char_level_val = getattr(char, "level", "N/A")
        char_experience_val = getattr(char, "experience", "N/A")
        char_unspent_xp_val = getattr(char, "unspent_xp", "N/A")
        char_hp_val = getattr(char, "hp", "N/A")
        char_max_health_val = getattr(char, "max_health", "N/A")
        char_class_i18n_val = getattr(char, 'class_i18n', {}) # Default to empty dict
        char_character_class_val = getattr(char, "character_class", "N/A")
        char_selected_language_val = getattr(char, "selected_language", "N/A")
        char_stats_val = getattr(char, "stats", None) # Can be None

        char_name = (char_name_i18n_val.get(lang,char_name_i18n_val.get("en",char_name_val)) if isinstance(char_name_i18n_val, dict) else char_name_val)
        details=[f"**Информация: {char_name}**", f"- ID: `{char_id_val}`", f"- Discord: `{char_discord_user_id_val}`",
                   f"- Уровень: {char_level_val}", f"- Опыт: {char_experience_val} (Непотраченный: {char_unspent_xp_val})",
                   f"- HP: {char_hp_val} / {char_max_health_val}"]

        cl_name_i18n = char_class_i18n_val if isinstance(char_class_i18n_val, dict) else {}
        cl_name = cl_name_i18n.get(lang, cl_name_i18n.get("en", char_character_class_val))
        details.append(f"- Класс: {cl_name or 'N/A'}"); details.append(f"- Язык: {char_selected_language_val or 'N/A'}")

        loc_str="N/A"; char_loc_id = getattr(char, 'current_location_id', None) # current_location_id can be None
        loc_inst = None
        if char_loc_id: # Only try to get instance if ID exists
            loc_inst = await location_manager.get_location_instance(guild_id_str,char_loc_id)

        if char_loc_id and loc_inst:
            loc_name_i18n = getattr(loc_inst, "name_i18n", {})
            loc_name_attr = getattr(loc_inst, "name", getattr(loc_inst, "id", "UNKNOWN_LOC_ID"))
            loc_n=(loc_name_i18n.get(lang,loc_name_i18n.get("en", loc_name_attr)) if isinstance(loc_name_i18n, dict) else loc_name_attr)
            loc_str=f"{loc_n} (`{char_loc_id}`)"
        elif char_loc_id: loc_str=f"Unknown (`{char_loc_id}`)"
        details.append(f"- Локация: {loc_str}")

        if char_stats_val and isinstance(char_stats_val, dict):
            details.extend(["\n**Базовые статы:**"]+[f"  - {s.replace('_',' ').capitalize()}: {v}" for s,v in char_stats_val.items()])

        eff_s_json = getattr(char,'effective_stats_json',None) # Can be None
        if eff_s_json:
            try:
                eff_s_data = json.loads(eff_s_json) if isinstance(eff_s_json, str) else eff_s_json
                if isinstance(eff_s_data, dict) and eff_s_data:
                     details.extend(["\n**Эффективные статы:**"]+[f"  - {s.replace('_',' ').capitalize()}: {v}" for s,v in eff_s_data.items()])
            except json.JSONDecodeError: details.append("\n- Эффективные статы: (ошибка JSON)")
        msg="\n".join(details); await interaction.followup.send(msg[:1950]+("..." if len(msg)>1950 else ""),ephemeral=True)

    @app_commands.command(name="master_view_map", description="ГМ: Просмотреть карту или детали локации.")
    @app_commands.describe(location_id="Опционально: ID локации для просмотра деталей.")
    @is_master_role()
    async def cmd_master_view_map(self, interaction: Interaction, location_id: Optional[str] = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        gid = str(interaction.guild_id)
        gm: Optional["GameManager"] = self.bot.game_manager
        lang = str(interaction.locale or "en")

        if not gm or not all(hasattr(gm,m) and getattr(gm,m) for m in ['location_manager','npc_manager','character_manager','event_manager']):
            await interaction.followup.send("**Мастер:** Один или несколько менеджеров недоступны.", ephemeral=True); return

        location_manager = cast("LocationManager", gm.location_manager)
        npc_manager = cast("NpcManager", gm.npc_manager)
        character_manager = cast("CharacterManager", gm.character_manager)
        event_manager = cast("EventManager", gm.event_manager)


        fmt = self.SimpleReportFormatter(gm, gid)

        if location_id is None:
            all_loc_data_any: List[Any] = []
            if hasattr(location_manager, 'get_all_location_instances') and callable(getattr(location_manager, 'get_all_location_instances')):
                 all_loc_data_any = await location_manager.get_all_location_instances(gid)
            elif hasattr(location_manager, '_location_instances') and isinstance(getattr(location_manager, '_location_instances', None), dict) and \
                 hasattr(location_manager, 'get_location_instance') and callable(getattr(location_manager, 'get_location_instance')):
                 loc_instances_dict = getattr(location_manager, '_location_instances', {}).get(gid, {})
                 if isinstance(loc_instances_dict, dict): # Should always be true if outer hasattr is true
                     loc_ids_to_fetch = list(loc_instances_dict.keys())
                     for loc_id_fetch in loc_ids_to_fetch:
                         loc_instance = await location_manager.get_location_instance(gid, loc_id_fetch) # Add await
                         if loc_instance: all_loc_data_any.append(loc_instance)
            else:
                logging.warning(f"LocationManager for guild {gid} missing 'get_all_location_instances' and viable fallback methods for map view.")


            if not all_loc_data_any:
                await interaction.followup.send("**Мастер:** Локаций не найдено.", ephemeral=True); return

            map_lines = ["**Все локации в гильдии:**"]
            for loc_obj_any in all_loc_data_any:
                loc_id_val = getattr(loc_obj_any, "id", "UNKNOWN_ID")
                loc_name_i18n_val = getattr(loc_obj_any,"name_i18n",{})
                loc_name_attr = getattr(loc_obj_any,"name", loc_id_val)
                loc_name = loc_name_i18n_val.get(lang, loc_name_i18n_val.get("en", loc_id_val)) if isinstance(loc_name_i18n_val,dict) else loc_name_attr
                map_lines.append(f"- `{loc_id_val}`: **{loc_name}**")

            msgs_to_send = []
            if not map_lines: await interaction.followup.send("**Мастер:** Нечего отображать.", ephemeral=True); return

            current_message_part = map_lines.pop(0)
            if map_lines: current_message_part += "\n"

            for line_item in map_lines:
                if len(current_message_part) + len(line_item) + 1 > 1950:
                    msgs_to_send.append(current_message_part.strip()); current_message_part = line_item
                else:
                    if not current_message_part.endswith("\n"): current_message_part += "\n"
                    current_message_part += line_item
            if current_message_part.strip(): msgs_to_send.append(current_message_part.strip())

            if not msgs_to_send: await interaction.followup.send("**Мастер:** Нечего отображать.", ephemeral=True); return

            for i, final_map_part in enumerate(msgs_to_send):
                page_prefix_map = f"(Часть {i+1}/{len(msgs_to_send)})\n" if len(msgs_to_send) > 1 else ""
                await interaction.followup.send(f"{page_prefix_map}{final_map_part}", ephemeral=True)
        else:
            loc = await location_manager.get_location_instance(gid, location_id)
            if not loc: await interaction.followup.send(f"**Мастер:** Локация `{location_id}` не найдена.", ephemeral=True); return

            loc_id_val = getattr(loc, "id", "UNKNOWN_ID")
            loc_name_i18n_val = getattr(loc,"name_i18n",{})
            loc_name_attr = getattr(loc,"name", loc_id_val)
            loc_name = loc_name_i18n_val.get(lang, loc_name_i18n_val.get("en", loc_id_val)) if isinstance(loc_name_i18n_val, dict) else loc_name_attr

            loc_desc_i18n = getattr(loc, "descriptions_i18n", {})
            loc_desc = loc_desc_i18n.get(lang, loc_desc_i18n.get("en","N/A")) if isinstance(loc_desc_i18n, dict) else "N/A"
            details = [f"**Детали локации: {loc_name} (`{loc_id_val}`)**", f"Описание: {loc_desc}"]

            loc_exits = getattr(loc,'exits',None)
            if loc_exits and isinstance(loc_exits,dict) and loc_exits:
                exit_lines = ["\n**Выходы:**"]
                for direction, exit_target in loc_exits.items():
                    target_id_str = ""
                    if isinstance(exit_target, dict):
                        target_id_str = exit_target.get("target_location_id", "Неизвестно")
                        exit_name_override_i18n = exit_target.get("name_i18n", {})
                        exit_name_override = exit_name_override_i18n.get(lang, exit_name_override_i18n.get("en")) if isinstance(exit_name_override_i18n, dict) else None
                        if exit_name_override:
                             exit_lines.append(f"- {direction.capitalize()}: {exit_name_override} (к `{target_id_str}`)")
                             continue
                    elif isinstance(exit_target, str): target_id_str = exit_target

                    exit_loc_name = await fmt._get_entity_name(target_id_str, 'location', lang) if target_id_str else "Неизвестно"
                    exit_lines.append(f"- {direction.capitalize()}: {exit_loc_name}" + (f" (`{target_id_str}`)" if target_id_str else ""))
                details.extend(exit_lines if len(exit_lines)>1 else ["- Выходов нет."])
            else: details.append("\n**Выходы:** Информации нет.")

            npcs_in_loc_list_any: List[Any] = await npc_manager.get_npcs_in_location(gid,loc_id_val)
            if npcs_in_loc_list_any:
                details.extend(["\n**NPC:**"]+[f"- {await fmt._get_entity_name(getattr(n,'id','N/A'),'npc',lang)}" for n in npcs_in_loc_list_any])

            chars_in_loc_list_any: List[Any] = await character_manager.get_characters_in_location(gid,loc_id_val)
            if chars_in_loc_list_any:
                details.extend(["\n**Персонажи:**"]+[f"- {await fmt._get_entity_name(getattr(c,'id','N/A'),'character',lang)} (Discord: <@{getattr(c,'discord_user_id','N/A')}>)" for c in chars_in_loc_list_any])

            active_loc_evts_any: List[Any] = []
            if hasattr(event_manager, 'get_active_events_for_location') and callable(getattr(event_manager, 'get_active_events_for_location')):
                active_loc_evts_any = await event_manager.get_active_events_for_location(gid, loc_id_val)
            elif hasattr(event_manager, 'get_active_events') and callable(getattr(event_manager, 'get_active_events')):
                logging.warning(f"EventManager for guild {gid} missing 'get_active_events_for_location'. Falling back to 'get_active_events'.")
                active_evts_all_any: List[Any] = await event_manager.get_active_events(gid)
                active_loc_evts_any=[e for e in active_evts_all_any if (hasattr(e,'location_id') and e.location_id==loc_id_val) or (hasattr(e,'state_variables') and isinstance(e.state_variables,dict) and e.state_variables.get('linked_location_id')==loc_id_val)]
            else:
                logging.warning(f"EventManager for guild {gid} missing event fetching methods for map view.")

            if active_loc_evts_any:
                details.extend(["\n**События:**"]+[f"- {await fmt._get_entity_name(getattr(evt,'id','N/A'),'event',lang)}" for evt in active_loc_evts_any])

            msg_content="\n".join(details)
            await interaction.followup.send(msg_content[:1950]+("..." if len(msg_content)>1950 else ""),ephemeral=True)

    @master_group.command(name="review_ai", description="Просмотреть ожидающие или неудачные AI генерации.")
    @app_commands.describe(pending_id="ID конкретной записи для просмотра (необязательно).")
    @is_master_role()
    async def cmd_master_review_ai(self, interaction: Interaction, pending_id: Optional[str] = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id_str = str(interaction.guild_id)
        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore[assignment]

        if not game_mngr or not hasattr(game_mngr, 'db_service') or not game_mngr.db_service:
            await interaction.followup.send("Ошибка: Сервис базы данных недоступен.", ephemeral=True); return

        db_service = game_mngr.db_service # db_service is now known to be not None and have DBService type

        if not pending_id:
            try:
                from bot.database.models.pending_generation import PendingGeneration, PendingStatus # Moved import here
                pending_records: List[PendingGeneration] = []
                if hasattr(db_service, "get_entities_by_conditions") and callable(getattr(db_service, "get_entities_by_conditions")):
                    pending_records = await db_service.get_entities_by_conditions(
                        PendingGeneration,
                        conditions={ "guild_id": guild_id_str, "status": {"in_": [PendingStatus.PENDING_MODERATION.value, PendingStatus.FAILED_VALIDATION.value]}},
                        order_by=[PendingGeneration.created_at.desc()],
                        limit=10
                    )
                else:
                    logging.warning(f"DBService for guild {guild_id_str} missing 'get_entities_by_conditions'. Cannot list pending AI generations.")
                    await interaction.followup.send("Функция просмотра списка генераций недоступна.", ephemeral=True); return


                if not pending_records:
                    await interaction.followup.send("Нет записей AI генераций, ожидающих модерации или с ошибками валидации.", ephemeral=True); return

                embed = discord.Embed(title="Ожидающие/Неудачные AI Генерации", color=discord.Color.orange())
                for record in pending_records:
                    status_val = getattr(record, 'status', PendingStatus.UNKNOWN.value)
                    status_emoji = "🟠" if status_val == PendingStatus.PENDING_MODERATION.value else "🔴"
                    created_at_val = getattr(record, 'created_at', None)
                    created_by_user_id_val = getattr(record, 'created_by_user_id', 'N/A')
                    request_type_val = getattr(record, 'request_type', 'N/A')
                    record_id_val = getattr(record, 'id', 'N/A')

                    field_value = (
                        f"**Тип:** {request_type_val}\n"
                        f"**Статус:** {status_emoji} {status_val}\n"
                        f"**Создано:** {created_at_val.strftime('%Y-%m-%d %H:%M:%S UTC') if created_at_val and hasattr(created_at_val, 'strftime') else 'N/A'}\n"
                        f"**Автор:** <@{created_by_user_id_val}> (ID: {created_by_user_id_val})"
                    )
                    embed.add_field(name=f"ID: `{record_id_val}`", value=field_value, inline=False)
                if not embed.fields:
                     await interaction.followup.send("Не найдено записей для отображения (после фильтрации).", ephemeral=True); return
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception as e:
                logging.error(f"Error listing pending AI generations: {e}", exc_info=True)
                await interaction.followup.send("Произошла ошибка при получении списка генераций.", ephemeral=True)
            return

        try:
            from bot.database.models.pending_generation import PendingGeneration # Moved import here
            record: Optional[PendingGeneration] = None
            if hasattr(db_service, "get_entity_by_pk") and callable(getattr(db_service, "get_entity_by_pk")):
                record = await db_service.get_entity_by_pk(
                    PendingGeneration, pk_value=pending_id, guild_id=guild_id_str
                )
            else:
                logging.warning(f"DBService for guild {guild_id_str} missing 'get_entity_by_pk'. Cannot fetch specific pending AI generation.")
                await interaction.followup.send("Функция просмотра конкретной генерации недоступна.", ephemeral=True); return


            if not record:
                await interaction.followup.send(f"Запись с ID `{pending_id}` не найдена.", ephemeral=True); return

            embed = discord.Embed(title=f"Детали AI Генерации: {record.id}", color=discord.Color.blue())
            embed.add_field(name="Guild ID", value=f"`{record.guild_id}`", inline=False)
            embed.add_field(name="Тип Запроса", value=str(record.request_type), inline=True)
            embed.add_field(name="Статус", value=str(record.status), inline=True)
            created_by_uid = record.created_by_user_id
            embed.add_field(name="Автор Запроса", value=f"<@{created_by_uid}> (`{created_by_uid}`)" if created_by_uid else "N/A", inline=True)

            created_at_val = record.created_at
            created_at_str = created_at_val.strftime('%Y-%m-%d %H:%M:%S UTC') if created_at_val and hasattr(created_at_val, 'strftime') else "N/A"
            embed.add_field(name="Время Создания", value=created_at_str, inline=False)

            request_params_json_val = record.request_params_json
            if request_params_json_val:
                try:
                    params_str = json.dumps(request_params_json_val, indent=2, ensure_ascii=False)
                    embed.add_field(name="Параметры Запроса", value=f"```json\n{params_str[:1000]}{'...' if len(params_str)>1000 else ''}\n```", inline=False)
                except Exception: embed.add_field(name="Параметры Запроса", value="Ошибка форматирования.", inline=False)

            raw_ai_output_text_val = record.raw_ai_output_text
            if raw_ai_output_text_val:
                embed.add_field(name="Raw AI Output (сниппет)", value=f"```\n{raw_ai_output_text_val[:1000]}{'...' if len(raw_ai_output_text_val)>1000 else ''}\n```", inline=False)

            parsed_data_json_val = record.parsed_data_json
            if parsed_data_json_val:
                try:
                    parsed_str = json.dumps(parsed_data_json_val, indent=2, ensure_ascii=False)
                    embed.add_field(name="Обработанные Данные", value=f"```json\n{parsed_str[:1000]}{'...' if len(parsed_str)>1000 else ''}\n```", inline=False)
                except Exception: embed.add_field(name="Обработанные Данные", value="Ошибка форматирования.", inline=False)

            validation_issues_json_val = record.validation_issues_json
            if validation_issues_json_val:
                try:
                    issues_str = json.dumps(validation_issues_json_val, indent=2, ensure_ascii=False)
                    embed.add_field(name="Ошибки Валидации", value=f"```json\n{issues_str[:1000]}{'...' if len(issues_str)>1000 else ''}\n```", inline=False)
                except Exception: embed.add_field(name="Ошибки Валидации", value="Ошибка форматирования.", inline=False)

            moderated_by_user_id_val = record.moderated_by_user_id
            if moderated_by_user_id_val:
                embed.add_field(name="Модератор", value=f"<@{moderated_by_user_id_val}> (`{moderated_by_user_id_val}`)", inline=True)
                moderated_at_val = record.moderated_at
                moderated_at_str = moderated_at_val.strftime('%Y-%m-%d %H:%M:%S UTC') if moderated_at_val and hasattr(moderated_at_val, 'strftime') else "N/A"
                embed.add_field(name="Время Модерации", value=moderated_at_str, inline=True)

            moderator_notes_i18n_val = record.moderator_notes_i18n
            if moderator_notes_i18n_val:
                try:
                    notes_str = json.dumps(moderator_notes_i18n_val, indent=2, ensure_ascii=False)
                    embed.add_field(name="Заметки Модератора", value=f"```json\n{notes_str[:1000]}{'...' if len(notes_str)>1000 else ''}\n```", inline=False)
                except: embed.add_field(name="Заметки Модератора", value="Ошибка форматирования.", inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logging.exception(f"Error reviewing AI generation {pending_id} in guild {guild_id_str}")
            await interaction.followup.send(f"Произошла ошибка при просмотре записи: {e}", ephemeral=True)

    @master_group.command(name="approve_ai", description="Одобрить AI генерацию для применения в игре.")
    @app_commands.describe(pending_id="ID записи для одобрения.")
    @is_master_role()
    async def cmd_master_approve_ai(self, interaction: Interaction, pending_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id_str = str(interaction.guild_id)
        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore[assignment]

        if not game_mngr or not hasattr(game_mngr, 'db_service') or not game_mngr.db_service:
            await interaction.followup.send("Ошибка: Сервис базы данных недоступен.", ephemeral=True); return

        db_service = game_mngr.db_service

        try:
            from bot.database.models.pending_generation import PendingGeneration, PendingStatus # Moved import here
            record_to_approve: Optional[PendingGeneration] = None
            success_db_update = False
            # session: Optional["AsyncSession"] = None # Not needed here with async with

            # get_session_method will be checked inside the try block
            get_session_method = getattr(db_service, "get_session", None)
            if not callable(get_session_method): # Check upfront
                logging.error(f"DBService for guild {guild_id_str} missing 'get_session' method.")
                await interaction.followup.send("Ошибка: Сервис базы данных неисправен (нет get_session).", ephemeral=True); return

            async with get_session_method() as session: # get_session_method is now known to be callable
                from bot.database import crud_utils
                record_to_approve = await crud_utils.get_entity_by_id(
                    db_session=session, model_class=PendingGeneration, entity_id=pending_id, guild_id=guild_id_str # Pass session
                )
                if not record_to_approve:
                    await interaction.followup.send(f"Запись с ID `{pending_id}` не найдена.", ephemeral=True); return

                current_status = record_to_approve.status
                if current_status not in [PendingStatus.PENDING_MODERATION.value, PendingStatus.FAILED_VALIDATION.value]:
                    await interaction.followup.send(f"Запись `{pending_id}` в статусе '{current_status}' не может быть одобрена.", ephemeral=True); return

                updates = {
                    "status": PendingStatus.APPROVED.value,
                    "moderated_by_user_id": str(interaction.user.id),
                    "moderated_at": datetime.datetime.now(datetime.timezone.utc)
                }
                updated_record_instance = await crud_utils.update_entity(
                    db_session=session, entity_instance=record_to_approve, data=updates, guild_id=guild_id_str
                )
                success_db_update = updated_record_instance is not None
                if success_db_update and updated_record_instance:
                    record_to_approve = updated_record_instance


            if success_db_update and record_to_approve:
                logging.info(f"AI Gen {pending_id} approved by {interaction.user.id}. Applying.")
                application_success = False
                if hasattr(game_mngr, "apply_approved_generation") and callable(getattr(game_mngr, "apply_approved_generation")):
                     application_success = await game_mngr.apply_approved_generation(pending_gen_id=pending_id, guild_id=guild_id_str)
                else:
                    logging.error(f"GameManager missing apply_approved_generation for {guild_id_str}")

                current_status_after_apply = PendingStatus.UNKNOWN.value
                # get_session_method is already confirmed callable
                async with get_session_method() as session_after_apply: # No need to re-check callable
                    from bot.database import crud_utils
                    updated_record_after_apply = await crud_utils.get_entity_by_id(
                        db_session=session_after_apply, model_class=PendingGeneration, entity_id=pending_id, guild_id=guild_id_str
                    )
                    if updated_record_after_apply: # Check if record still exists
                        current_status_after_apply = updated_record_after_apply.status


                record_req_type = record_to_approve.request_type # record_to_approve is from outside the session, might be stale
                                                                # but request_type is unlikely to change.
                if application_success:
                    await interaction.followup.send(f"✅ AI ID `{pending_id}` (Тип: {record_req_type}) одобрено и применено.", ephemeral=True)
                else:
                    await interaction.followup.send(f"⚠️ AI ID `{pending_id}` (Тип: {record_req_type}) одобрено, но применение не удалось/ожидает. Статус: {current_status_after_apply}.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Не удалось обновить статус для AI ID `{pending_id}` или запись не найдена после обновления.", ephemeral=True)
        except Exception as e:
            logging.error(f"Error approving AI generation {pending_id}: {e}", exc_info=True)
            await interaction.followup.send(f"Ошибка одобрения: {e}", ephemeral=True)

    @master_group.command(name="reject_ai", description="Отклонить AI генерацию.")
    @app_commands.describe(pending_id="ID записи для отклонения.", reason="Причина отклонения (необязательно).")
    @is_master_role()
    async def cmd_master_reject_ai(self, interaction: Interaction, pending_id: str, reason: Optional[str] = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id_str = str(interaction.guild_id)
        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore[assignment]

        if not game_mngr or not hasattr(game_mngr, 'db_service') or not game_mngr.db_service:
            await interaction.followup.send("Ошибка: Сервис базы данных недоступен.", ephemeral=True); return
        db_service = game_mngr.db_service
        from bot.database.models.pending_generation import PendingGeneration, PendingStatus # Moved import
        record_to_reject: Optional[PendingGeneration] = None

        if hasattr(db_service, "get_entity_by_pk") and callable(getattr(db_service, "get_entity_by_pk")):
            record_to_reject = await db_service.get_entity_by_pk(
                PendingGeneration, pk_value=pending_id, guild_id=guild_id_str
            )
        else:
            logging.warning(f"DBService for guild {guild_id_str} missing 'get_entity_by_pk'. Cannot fetch for rejection.")
            await interaction.followup.send("Функция отклонения недоступна (нет get_entity_by_pk).", ephemeral=True); return


        if not record_to_reject:
            await interaction.followup.send(f"Запись с ID `{pending_id}` не найдена.", ephemeral=True); return

        try:
            current_status = record_to_reject.status
            if current_status not in [PendingStatus.PENDING_MODERATION.value, PendingStatus.FAILED_VALIDATION.value]:
                await interaction.followup.send(f"Запись `{pending_id}` в статусе '{current_status}' не может быть отклонена.", ephemeral=True); return

            updates: Dict[str, Any] = {
                "status": PendingStatus.REJECTED.value,
                "moderated_by_user_id": str(interaction.user.id),
                "moderated_at": datetime.datetime.now(datetime.timezone.utc)
            }
            if reason:
                main_lang = "en"
                if hasattr(game_mngr, "get_rule") and callable(getattr(game_mngr, "get_rule")):
                     main_lang_res = await game_mngr.get_rule(guild_id_str, "default_language", "en")
                     if main_lang_res: main_lang = main_lang_res


                current_notes_val = record_to_reject.moderator_notes_i18n
                current_notes = current_notes_val if isinstance(current_notes_val, dict) else {}
                current_notes["rejection_reason"] = {main_lang: reason}
                updates["moderator_notes_i18n"] = current_notes

            success_update = False
            if hasattr(db_service, "update_entity_by_pk") and callable(getattr(db_service, "update_entity_by_pk")):
                success_update = await db_service.update_entity_by_pk(PendingGeneration, pending_id, updates, guild_id=guild_id_str)
            else:
                 logging.warning(f"DBService for guild {guild_id_str} missing 'update_entity_by_pk'. Cannot update for rejection.")
                 await interaction.followup.send("Функция отклонения недоступна (нет update_entity_by_pk).", ephemeral=True); return



            if success_update:
                logging.info(f"AI Gen {pending_id} rejected by {interaction.user.id}. Reason: {reason or 'N/A'}")
                record_request_type = record_to_reject.request_type
                await interaction.followup.send(f"🚫 AI ID `{pending_id}` (Тип: {record_request_type}) отклонено. Причина: {reason or 'N/A'}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Не удалось обновить статус для AI ID `{pending_id}`.", ephemeral=True)
        except Exception as e:
            logging.error(f"Error rejecting AI generation {pending_id}: {e}", exc_info=True)
            await interaction.followup.send(f"Ошибка отклонения: {e}", ephemeral=True)

    @master_group.command(name="edit_ai", description="Редактировать JSON данные ожидающей AI-генерации и повторно валидировать.")
    @app_commands.describe(
        pending_id="ID записи для редактирования.",
        json_data="Новые JSON данные для поля 'parsed_data_json'."
    )
    @is_master_role()
    async def cmd_master_edit_ai(self, interaction: Interaction, pending_id: str, json_data: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id_str = str(interaction.guild_id)
        game_mngr: Optional["GameManager"] = self.bot.game_manager # type: ignore[assignment]

        if not game_mngr or not hasattr(game_mngr, 'db_service') or not game_mngr.db_service:
            await interaction.followup.send("Ошибка: Сервис базы данных недоступен.", ephemeral=True); return
        db_service = game_mngr.db_service # db_service is now known to be not None

        try:
            record_to_edit: Optional["PendingGeneration"] = None
            session_initial: Optional["AsyncSession"] = None

            get_session_method = getattr(db_service, "get_session", None)
            if not callable(get_session_method):
                logging.error(f"DBService for guild {guild_id_str} missing 'get_session' method for edit_ai.")
                await interaction.followup.send("Ошибка: Сервис базы данных неисправен (нет get_session).", ephemeral=True); return

            from bot.database.models.pending_generation import PendingGeneration, PendingStatus # Moved import
            from bot.ai.ai_response_validator import parse_and_validate_ai_response # Moved import
            from bot.ai.ai_data_models import GenerationType # Moved import

            async with get_session_method() as session_initial: # get_session_method is now known to be callable
                from bot.database import crud_utils
                record_to_edit = await crud_utils.get_entity_by_id(
                    db_session=session_initial, model_class=PendingGeneration, entity_id=pending_id, guild_id=guild_id_str
                )


            if not record_to_edit:
                await interaction.followup.send(f"Запись с ID `{pending_id}` не найдена.", ephemeral=True); return

            current_status_rec = record_to_edit.status
            if current_status_rec not in [PendingStatus.PENDING_MODERATION.value, PendingStatus.FAILED_VALIDATION.value]:
                await interaction.followup.send(f"Запись `{pending_id}` в статусе '{current_status_rec}' не может быть отредактирована.", ephemeral=True); return
                
            new_parsed_data: Optional[Any] = None
            try: new_parsed_data = json.loads(json_data)
            except json.JSONDecodeError as e:
                await interaction.followup.send(f"JSON некорректен: {e}", ephemeral=True); return

            record_request_type_str = record_to_edit.request_type
            if not record_request_type_str or not isinstance(record_request_type_str, str):
                await interaction.followup.send(f"У записи `{pending_id}` неверный тип запроса. Редактирование невозможно.", ephemeral=True); return

            try: record_request_type_enum = GenerationType[record_request_type_str.upper()]
            except KeyError:
                await interaction.followup.send(f"Неизвестный тип запроса '{record_request_type_str}' для записи `{pending_id}`.", ephemeral=True); return

            is_list_type = record_request_type_enum in [
                GenerationType.LIST_OF_QUESTS, GenerationType.LIST_OF_NPCS,
                GenerationType.LIST_OF_ITEMS, GenerationType.LIST_OF_LOCATIONS,
                GenerationType.LIST_OF_EVENTS
            ]

            if is_list_type and not isinstance(new_parsed_data, list):
                 await interaction.followup.send(f"Для '{record_request_type_enum.value}' ожидался JSON массив (list).", ephemeral=True); return
            elif not is_list_type and not isinstance(new_parsed_data, dict):
                 await interaction.followup.send(f"Для '{record_request_type_enum.value}' ожидался JSON объект (dict).", ephemeral=True); return

            validated_data_after_edit, validation_issues_after_edit = await parse_and_validate_ai_response(
                raw_ai_output_text=json_data,
                guild_id=guild_id_str,
                request_type=record_request_type_enum,
                game_manager=game_mngr
            )

            updates: Dict[str, Any] = {
                "parsed_data_json": validated_data_after_edit,
                "validation_issues_json": validation_issues_after_edit,
                "status": PendingStatus.PENDING_MODERATION.value if not validation_issues_after_edit else PendingStatus.FAILED_VALIDATION.value,
                "moderated_by_user_id": str(interaction.user.id),
                "moderated_at": datetime.datetime.now(datetime.timezone.utc)
            }

            current_notes_val = record_to_edit.moderator_notes_i18n
            current_notes = current_notes_val if isinstance(current_notes_val, dict) else {}
            edit_history = current_notes.get("edit_history", [])
            if not isinstance(edit_history, list): edit_history = []

            edit_history.append({
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "editor_id": str(interaction.user.id), "action": "edited_data",
                "previous_status": str(current_status_rec), "new_status": updates["status"]
            })
            current_notes["edit_history"] = edit_history
            updates["moderator_notes_i18n"] = current_notes

            success_update_edit = False
            # get_session_method is already confirmed callable
            try:
                async with get_session_method() as session_for_update: # get_session_method is now known to be callable
                    from bot.database import crud_utils
                    record_for_update_in_session = await crud_utils.get_entity_by_id(
                            db_session=session_for_update, model_class=PendingGeneration, entity_id=pending_id, guild_id=guild_id_str
                    )
                    if record_for_update_in_session:
                        updated_record_instance = await crud_utils.update_entity(
                            db_session=session_for_update, entity_instance=record_for_update_in_session, data=updates, guild_id=guild_id_str
                        )
                        success_update_edit = updated_record_instance is not None
                    else:
                        logging.error(f"Record {pending_id} disappeared before update in edit_ai for guild {guild_id_str}.")
            except Exception as e_update:
                logging.exception(f"Error during database update session for edit_ai {pending_id} in guild {guild_id_str}: {e_update}")
                success_update_edit = False

            if success_update_edit:
                msg = f"⚙️ AI ID `{pending_id}` (Тип: {record_request_type_enum.value}) обновлено. Статус: {updates['status']}."
                if validation_issues_after_edit:
                    issues_summary = "; ".join([f"{str(issue.get('loc', 'N/A'))}: {issue.get('msg', 'Unknown')}" for issue in validation_issues_after_edit[:3]])
                    msg += f"\nПроблемы валидации (первые 3): {issues_summary}"
                    if len(validation_issues_after_edit) > 3: msg += "..."
                logging.info(f"AI Gen {pending_id} edited by {interaction.user.id}. New status: {updates['status']}.")
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Не удалось сохранить изменения для AI ID `{pending_id}`.", ephemeral=True)
        except Exception as e:
            logging.error(f"Error editing AI generation {pending_id}: {e}", exc_info=True)
            await interaction.followup.send(f"Ошибка редактирования: {e}", ephemeral=True)

async def setup(bot: "RPGBot"):
    await bot.add_cog(GMAppCog(bot))
    logging.info("GMAppCog loaded.")
