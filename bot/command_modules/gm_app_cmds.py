import discord # Ensure discord is imported for discord.Interaction
from discord import Interaction, app_commands
from discord.ext import commands
import traceback
from bot.command_modules.game_setup_cmds import is_master_or_admin_check
# Removed duplicate import of is_master_or_admin_check
import json # For parsing parameters_json
from typing import TYPE_CHECKING, Optional, Dict, Any, List # Added List
import uuid # For report_id

from bot.game.managers.undo_manager import UndoManager

# For Pydantic models if used in type hints for params_json structures
# from bot.api.schemas.rule_config_schemas import RuleConfigData # Only if directly used

# For Simulators and ReportFormatters (imported dynamically or within methods to avoid circulars if complex)
# from bot.game.simulation import BattleSimulator, QuestSimulator, ActionConsequenceModeler
# from bot.game.services.report_formatter import ReportFormatter
# from bot.game.models.location import Location as LocationModel # if type hinting specific models
# from bot.game.models.npc import NPC as NPCModelType

if TYPE_CHECKING:
    from bot.bot_core import RPGBot
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.api.schemas.rule_config_schemas import RuleConfigData


class GMAppCog(commands.Cog, name="GM App Commands"):
    def __init__(self, bot: "RPGBot"):
        self.bot = bot

    @app_commands.command(name="gm_simulate", description="ГМ: Запустить один шаг симуляции мира.")
    async def cmd_gm_simulate(self, interaction: Interaction):
        if not hasattr(self.bot, 'game_manager') or not self.bot.game_manager or not hasattr(self.bot.game_manager, '_settings'):
            await interaction.response.send_message("**Мастер:** Конфигурация игры не загружена.", ephemeral=True)
            return
        bot_admin_ids = [str(id_val) for id_val in self.bot.game_manager._settings.get('bot_admins', [])]
        if str(interaction.user.id) not in bot_admin_ids: # Basic check, consider standardizing
            await interaction.response.send_message("**Мастер:** Только Истинный Мастер может управлять ходом времени!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id: await interaction.followup.send("**Мастер:** Эту команду можно использовать только на сервере.", ephemeral=True); return
        game_mngr = self.bot.game_manager
        if game_mngr:
            try:
                await game_mngr.trigger_manual_simulation_tick(server_id=str(interaction.guild_id))
                await interaction.followup.send("**Мастер:** Шаг симуляции мира (ручной) завершен!")
            except Exception as e: print(f"Error in cmd_gm_simulate (Cog): {e}"); traceback.print_exc(); await interaction.followup.send(f"**Мастер:** Ошибка при симуляции: {e}", ephemeral=True)
        else: await interaction.followup.send("**Мастер:** GameManager недоступен.", ephemeral=True)

    @app_commands.command(name="resolve_conflict", description="ГМ: Разрешить ожидающий конфликт.")
    @app_commands.describe(conflict_id="ID конфликта.", outcome_type="Тип исхода.", parameters_json="JSON параметры (опц).")
    async def cmd_resolve_conflict(self, interaction: discord.Interaction, conflict_id: str, outcome_type: str, parameters_json: Optional[str] = None):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id: await interaction.followup.send("**Мастер:** Команда для сервера.", ephemeral=True); return
        game_mngr = self.bot.game_manager
        if not game_mngr or not game_mngr.conflict_resolver or not game_mngr.game_log_manager: await interaction.followup.send("**Мастер:** ConflictResolver/GameLogManager недоступен.", ephemeral=True); return
        parsed_params = None
        if parameters_json:
            try: parsed_params = json.loads(parameters_json)
            except json.JSONDecodeError as e: await interaction.followup.send(f"**Мастер:** Ошибка JSON: {e}", ephemeral=True); return
            if not isinstance(parsed_params, dict): await interaction.followup.send("**Мастер:** JSON должен быть объектом.", ephemeral=True); return
        try:
            res = await game_mngr.conflict_resolver.process_master_resolution(conflict_id, outcome_type, parsed_params)
            msg = f"Конфликт '{conflict_id}' разрешен как '{outcome_type}'.\n{res.get('message','Детали не предоставлены.')}" if res.get("success") else f"Ошибка разрешения '{conflict_id}':\n{res.get('message','Неизвестная ошибка.')}"
            if res.get("success"):
                log_d = {"conflict_id":conflict_id,"outcome":outcome_type,"params":parsed_params,"gm_id":str(interaction.user.id),"gm_name":interaction.user.name, "desc_msg": f"GM {interaction.user.name} resolved conflict {conflict_id} as {outcome_type}."}
                await game_mngr.game_log_manager.log_event(str(interaction.guild_id),"gm_action_resolve_conflict",details=log_d)
            await interaction.followup.send(f"**Мастер:** {msg}", ephemeral=True)
        except Exception as e: traceback.print_exc(); await interaction.followup.send(f"**Мастер:** Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="gm_delete_character", description="ГМ: Удалить данные персонажа по его ID.")
    @app_commands.describe(character_id="ID персонажа (Character object UUID) для удаления.")
    async def cmd_gm_delete_character(self, interaction: discord.Interaction, character_id: str):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id: await interaction.followup.send("**Мастер:** Команда для сервера.", ephemeral=True); return
        guild_id_str, game_mngr = str(interaction.guild_id), self.bot.game_manager
        if not game_mngr or not game_mngr.character_manager or not game_mngr.game_log_manager: await interaction.followup.send("**Мастер:** CharacterManager/GameLogManager недоступен.", ephemeral=True); return
        try:
            if removed_char_id := await game_mngr.character_manager.remove_character(character_id,guild_id_str):
                log_d = {"char_id":character_id,"deleter_gm_id":str(interaction.user.id),"deleter_gm_name":interaction.user.name, "desc_msg":f"GM {interaction.user.name} initiated deletion for char ID {character_id}."}
                await game_mngr.game_log_manager.log_event(guild_id_str,"gm_action_delete_character",details=log_d)
                await interaction.followup.send(f"**Мастер:** Персонаж '{removed_char_id}' помечен для удаления.", ephemeral=True)
            else: await interaction.followup.send(f"**Мастер:** Персонаж '{character_id}' не найден/не удален.", ephemeral=True)
        except Exception as e: traceback.print_exc(); await interaction.followup.send(f"**Мастер:** Ошибка: {e}", ephemeral=True)

    @app_commands.command(name="master_undo", description="ГМ: Отменить последнее событие для игрока или партии.")
    @app_commands.describe(num_steps="Количество шагов (по умолчанию 1).", entity_id="ID игрока/партии (обязательно).")
    async def cmd_master_undo(self, interaction: Interaction, num_steps: Optional[int] = 1, entity_id: Optional[str] = None):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id: await interaction.followup.send("**Мастер:** Команда для сервера.", ephemeral=True); return
        guild_id_str, game_mngr = str(interaction.guild_id), self.bot.game_manager
        if not game_mngr or not game_mngr.undo_manager or not game_mngr.character_manager or not game_mngr.party_manager: await interaction.followup.send("**Мастер:** UndoManager/CharacterManager/PartyManager недоступен.", ephemeral=True); return
        if not entity_id: await interaction.followup.send("**Мастер:** ID игрока/партии обязателен.", ephemeral=True); return
        num_steps = num_steps if num_steps and num_steps >= 1 else 1
        action_type, success = "unknown", False
        if game_mngr.character_manager.get_character(guild_id_str, entity_id): action_type="player"; success = await game_mngr.undo_manager.undo_last_player_event(guild_id_str,entity_id,num_steps)
        elif game_mngr.party_manager.get_party(guild_id_str, entity_id): action_type="party"; success = await game_mngr.undo_manager.undo_last_party_event(guild_id_str,entity_id,num_steps)
        if action_type=="unknown": await interaction.followup.send(f"**Мастер:** Сущность '{entity_id}' не найдена.", ephemeral=True); return
        msg = f"**Мастер:** Последние {num_steps} событий для {action_type} '{entity_id}' {'отменены' if success else 'не удалось отменить'}."
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="master_goto_log", description="ГМ: Отменить события до указанной записи лога.")
    @app_commands.describe(log_id_target="ID целевой записи лога.", entity_id="Опц: ID игрока/партии.")
    async def cmd_master_goto_log(self, interaction: Interaction, log_id_target: str, entity_id: Optional[str] = None):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id: await interaction.followup.send("**Мастер:** Команда для сервера.", ephemeral=True); return
        guild_id_str, game_mngr = str(interaction.guild_id), self.bot.game_manager
        if not game_mngr or not game_mngr.undo_manager: await interaction.followup.send("**Мастер:** UndoManager недоступен.", ephemeral=True); return
        entity_type_str = None
        if entity_id:
            if game_mngr.character_manager and game_mngr.character_manager.get_character(guild_id_str, entity_id): entity_type_str="player"
            elif game_mngr.party_manager and game_mngr.party_manager.get_party(guild_id_str, entity_id): entity_type_str="party"
            else: await interaction.followup.send(f"**Мастер:** Сущность '{entity_id}' не найдена.", ephemeral=True); return
        success = await game_mngr.undo_manager.undo_to_log_entry(guild_id_str,log_id_target,entity_id,entity_type_str)
        msg = f"**Мастер:** События до лога '{log_id_target}'" + (f" для '{entity_id}'" if entity_id else " для гильдии")
        await interaction.followup.send(f"{msg} {'успешно отменены' if success else 'не удалось отменить'}.", ephemeral=True)

    @app_commands.command(name="master_undo_event", description="ГМ: Отменить конкретное событие по ID из лога.")
    @app_commands.describe(log_id="ID записи лога для отмены.")
    async def cmd_master_undo_event(self, interaction: Interaction, log_id: str):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id: await interaction.followup.send("**Мастер:** Команда для сервера.", ephemeral=True); return
        guild_id_str, game_mngr = str(interaction.guild_id), self.bot.game_manager
        if not game_mngr or not game_mngr.undo_manager: await interaction.followup.send("**Мастер:** UndoManager недоступен.", ephemeral=True); return
        if not log_id: await interaction.followup.send("**Мастер:** ID лога не указан.", ephemeral=True); return
        success = await game_mngr.undo_manager.undo_specific_log_entry(guild_id_str, log_id)
        await interaction.followup.send(f"**Мастер:** Событие '{log_id}' {'успешно отменено' if success else 'не удалось отменить'}.", ephemeral=True)

    # --- Start of Consolidated Commands ---

    @app_commands.command(name="master_edit_npc", description="ГМ: Редактировать атрибут NPC.")
    @app_commands.describe(npc_id="ID NPC для редактирования.",
                           attribute="Атрибут для изменения (например, name_i18n.en, stats.hp, location_id).",
                           value="Новое значение для атрибута.")
    async def cmd_master_edit_npc(self, interaction: Interaction, npc_id: str, attribute: str, value: str):
        if not await is_master_or_admin_check(interaction):
            await interaction.response.send_message("**Мастер:** У вас нет прав для выполнения этой команды.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        guild_id = str(interaction.guild_id)
        game_mngr = self.bot.game_manager

        if not game_mngr or not game_mngr.npc_manager or not game_mngr.game_log_manager:
            await interaction.followup.send("**Мастер:** NpcManager или GameLogManager недоступен. Пожалуйста, обратитесь к администратору.", ephemeral=True)
            return

        npc = game_mngr.npc_manager.get_npc(guild_id, npc_id)
        if not npc:
            await interaction.followup.send(f"**Мастер:** NPC с ID '{npc_id}' не найден в этой гильдии.", ephemeral=True)
            return

        try:
            original_value_str = "N/A"
            processed_value: Any = value # Value to be stored, potentially type-converted
            log_value = value # Value for logging, usually string

            # Determine NPC name for logging (best effort)
            lang_for_log = str(interaction.locale or game_mngr.get_default_bot_language() or "en")
            npc_name_for_log = npc.id
            if hasattr(npc, 'name_i18n') and isinstance(npc.name_i18n, dict):
                npc_name_for_log = npc.name_i18n.get(lang_for_log, npc.name_i18n.get("en", npc.id))
            elif hasattr(npc, 'name'):
                npc_name_for_log = npc.name

            update_successful = False

            # Handling i18n fields: name_i18n, description_i18n, persona_i18n
            if attribute.startswith("name_i18n.") or \
               attribute.startswith("description_i18n.") or \
               attribute.startswith("persona_i18n."):
                parts = attribute.split(".", 1)
                field_name = parts[0]  # e.g., "name_i18n"
                lang_code = parts[1]   # e.g., "en"

                if not hasattr(npc, field_name):
                    await interaction.followup.send(f"**Мастер:** У NPC нет атрибута '{field_name}'.", ephemeral=True)
                    return

                current_i18n_dict = getattr(npc, field_name, {})
                if not isinstance(current_i18n_dict, dict): # Ensure it's a dict
                    current_i18n_dict = {}

                original_value_str = str(current_i18n_dict.get(lang_code, "N/A"))
                current_i18n_dict[lang_code] = value
                processed_value = current_i18n_dict

                # Use a generic update method if available, or setattr and mark_dirty
                if hasattr(game_mngr.npc_manager, 'update_npc_field'):
                    update_successful = await game_mngr.npc_manager.update_npc_field(guild_id, npc_id, field_name, processed_value)
                else: # Fallback to direct setattr if NpcManager does not have update_npc_field
                    setattr(npc, field_name, processed_value)
                    game_mngr.npc_manager.mark_npc_dirty(guild_id, npc_id) # Assumes mark_npc_dirty exists
                    update_successful = True
                log_value = f"{value} (lang: {lang_code})"

            # Handling stats fields: stats.hp, stats.base_strength, etc.
            elif attribute.startswith("stats."):
                stat_key = attribute.split(".", 1)[1] # e.g., "hp"

                current_stats = npc.stats if isinstance(npc.stats, dict) else {}
                original_value_str = str(current_stats.get(stat_key, "N/A"))

                # Attempt type conversion based on existing value or common types
                target_type = None
                if stat_key in current_stats and current_stats[stat_key] is not None:
                    target_type = type(current_stats[stat_key])

                if target_type == bool:
                    processed_value = value.lower() in ['true', '1', 'yes']
                elif target_type == int:
                    try: processed_value = int(value)
                    except ValueError: await interaction.followup.send(f"**Мастер:** Неверное значение для '{attribute}'. Ожидалось целое число.", ephemeral=True); return
                elif target_type == float:
                    try: processed_value = float(value)
                    except ValueError: await interaction.followup.send(f"**Мастер:** Неверное значение для '{attribute}'. Ожидалось число.", ephemeral=True); return
                else: # Default to trying int, then float, then string
                    try: processed_value = int(value)
                    except ValueError:
                        try: processed_value = float(value)
                        except ValueError: processed_value = value # Keep as string

                update_successful = await game_mngr.npc_manager.update_npc_stats(guild_id, npc_id, {stat_key: processed_value})
                log_value = str(processed_value)

            # Handling direct fields like location_id, faction_id
            elif attribute in ["location_id", "faction_id", "archetype", "role"]: # Add other simple fields if needed
                if not hasattr(npc, attribute):
                    await interaction.followup.send(f"**Мастер:** У NPC нет атрибута '{attribute}'.", ephemeral=True)
                    return

                original_value_str = str(getattr(npc, attribute, "N/A"))
                processed_value = value if value.lower() not in ["none", "null", ""] else None

                if attribute == "location_id" and processed_value is not None: # Validate location exists
                    if not game_mngr.location_manager or not game_mngr.location_manager.get_location_instance(guild_id, processed_value):
                        await interaction.followup.send(f"**Мастер:** Локация с ID '{processed_value}' не найдена.", ephemeral=True)
                        return

                # Use a generic update method if available
                if hasattr(game_mngr.npc_manager, 'update_npc_field'):
                    update_successful = await game_mngr.npc_manager.update_npc_field(guild_id, npc_id, attribute, processed_value)
                else: # Fallback
                    setattr(npc, attribute, processed_value)
                    game_mngr.npc_manager.mark_npc_dirty(guild_id, npc_id)
                    update_successful = True
                log_value = str(processed_value)

            else:
                await interaction.followup.send(f"**Мастер:** Атрибут '{attribute}' не поддерживается для редактирования этим способом.", ephemeral=True)
                return

            if update_successful:
                # For stats, trigger recalculation if NpcManager doesn't do it internally
                if attribute.startswith("stats.") and hasattr(game_mngr.npc_manager, 'trigger_stats_recalculation'):
                    await game_mngr.npc_manager.trigger_stats_recalculation(guild_id, npc_id)

                log_details = {
                    "npc_id": npc_id,
                    "npc_name": npc_name_for_log, # Use derived name
                    "attribute_changed": attribute,
                    "old_value": original_value_str,
                    "new_value": log_value, # Use stringified processed value for log
                    "gm_user_id": str(interaction.user.id),
                    "gm_user_name": interaction.user.name
                }
                await game_mngr.game_log_manager.log_event(
                    guild_id=guild_id,
                    event_type="gm_npc_edit",
                    details=log_details
                )
                await interaction.followup.send(f"**Мастер:** NPC '{npc_name_for_log}' (`{npc_id}`) успешно обновлен. Атрибут '{attribute}' изменен с '{original_value_str}' на '{log_value}'.", ephemeral=True)
            else:
                await interaction.followup.send(f"**Мастер:** Не удалось обновить атрибут '{attribute}' для NPC '{npc_name_for_log}' (`{npc_id}`). Проверьте логи для деталей.", ephemeral=True)

        except Exception as e:
            traceback.print_exc()
            await interaction.followup.send(f"**Мастер:** Произошла внутренняя ошибка при редактировании NPC: {e}", ephemeral=True)

    @app_commands.command(name="master_edit_character", description="ГМ: Редактировать атрибут персонажа.")
    @app_commands.describe(character_id="ID персонажа/Discord ID.", attribute="Атрибут (name_i18n.en, stats.hp, level, etc.).", value="Новое значение.")
    async def cmd_master_edit_character(self, interaction: Interaction, character_id: str, attribute: str, value: str):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True, thinking=True)
        gid, gm = str(interaction.guild_id), self.bot.game_manager
        if not gm or not gm.character_manager or not gm.game_log_manager or not gm.location_manager: await interaction.followup.send("**Мастер:** Необходимые менеджеры недоступны.", ephemeral=True); return
        char = gm.character_manager.get_character_by_discord_id(gid, int(character_id)) if character_id.isdigit() else gm.character_manager.get_character(gid, character_id)
        if not char and character_id.isdigit(): char = gm.character_manager.get_character(gid, character_id)
        if not char: await interaction.followup.send(f"**Мастер:** Персонаж '{character_id}' не найден.", ephemeral=True); return
        try:
            orig_val_str="N/A"; processed_val: Any =value; lang=str(interaction.locale or "en")
            char_name_log = char.name_i18n.get(lang, char.name_i18n.get("en",char.id)) if hasattr(char,"name_i18n") and char.name_i18n else getattr(char,"name",char.id)
            if attribute.startswith("name_i18n."):
                parts=attribute.split(".",1); field,code=parts[0],parts[1]; i18n_d=getattr(char,field,{}); i18n_d=i18n_d if isinstance(i18n_d,dict) else {}
                orig_val_str=i18n_d.get(code,"N/A"); i18n_d[code]=value; setattr(char,field,i18n_d)
                if code!='en' and 'en' not in i18n_d: i18n_d['en']=value
                gm.character_manager.mark_character_dirty(gid,char.id)
            elif attribute.startswith("stats.") or attribute in ["level","experience","unspent_xp","hp","max_health","is_alive","gold","character_class","selected_language"]:
                stat_key_for_update=attribute
                _orig_val_for_type = char.stats.get(attribute.split(".",1)[1]) if attribute.startswith("stats.") else getattr(char,attribute,None)
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
                elif attribute=="is_alive": processed_val = True if value.lower() in ["true","1","yes"] else (False if value.lower() in ["false","0","no"] else "INVALID_BOOL")
                if processed_val == "INVALID_BOOL": await interaction.followup.send("**Мастер:** Неверное значение для 'is_alive'. True/False.",ephemeral=True); return
                if attribute in ["character_class","selected_language"]: setattr(char,attribute,processed_val); gm.character_manager.mark_character_dirty(gid,char.id); await gm.character_manager.trigger_stats_recalculation(gid,char.id) if attribute=="character_class" else None
                else:
                    if not await gm.character_manager.update_character_stats(gid,char.id,{stat_key_for_update:processed_val}): await interaction.followup.send(f"**Мастер:** Ошибка обновления '{attribute}'.",ephemeral=True); return
            elif attribute=="location_id":
                orig_val_str=str(char.location_id if char.location_id else "N/A"); processed_val=value if value.lower()!="none" else None
                if not await gm.character_manager.update_character_location(char.id,processed_val,gid): await interaction.followup.send(f"**Мастер:** Ошибка обновления location_id.",ephemeral=True); return
            else: await interaction.followup.send(f"**Мастер:** Атрибут '{attribute}' не поддерживается.",ephemeral=True); return
            log_d={"char_id":char.id,"char_name":char_name_log,"discord_id":str(char.discord_user_id),"attr":attribute,"old":orig_val_str,"new":str(processed_val),"gm_id":str(interaction.user.id),"gm_name":interaction.user.name}
            await gm.game_log_manager.log_event(gid,"gm_edit_character",details=log_d)
            await interaction.followup.send(f"**Мастер:** Персонаж '{char_name_log}' (`{char.id}`) обновлен: '{attribute}' с '{orig_val_str}' на '{str(processed_val)}'.",ephemeral=True)
        except Exception as e: traceback.print_exc(); await interaction.followup.send(f"**Мастер:** Ошибка: {e}",ephemeral=True)

    @app_commands.command(name="master_edit_item", description="ГМ: Редактировать атрибут экземпляра предмета.")
    @app_commands.describe(item_instance_id="ID экземпляра.", attribute="Атрибут (owner_id, quantity, state_variables.key).", value="Новое значение.")
    async def cmd_master_edit_item(self, interaction: Interaction, item_instance_id: str, attribute: str, value: str):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True, thinking=True)
        gid, gm = str(interaction.guild_id), self.bot.game_manager
        if not gm or not gm.item_manager or not gm.game_log_manager: await interaction.followup.send("**Мастер:** ItemManager/GameLogManager недоступен.", ephemeral=True); return
        item = gm.item_manager.get_item_instance(gid, item_instance_id)
        if not item: await interaction.followup.send(f"**Мастер:** Предмет '{item_instance_id}' не найден.", ephemeral=True); return
        try:
            orig_val_str, payload, proc_val = "N/A", {}, value; lang = str(interaction.locale or "en")
            item_tpl_name = item.template_id
            if tpl := gm.item_manager.get_item_template(item.template_id): item_tpl_name=tpl.get("name_i18n",{}).get(lang,tpl.get("en",item.template_id))
            if attribute.startswith("state_variables."):
                if not isinstance(item.state_variables,dict): item.state_variables={}
                key=attribute.split(".",1)[1]; orig_val=item.state_variables.get(key); orig_val_str=str(orig_val) if orig_val is not None else "N/A"
                try: proc_val=type(orig_val)(value) if orig_val is not None and not isinstance(orig_val,str) else (int(value) if value.isdigit() else (float(value) if value.replace('.','',1).isdigit() else value))
                except: proc_val=value
                item.state_variables[key]=proc_val; payload["state_variables"]=item.state_variables
            elif attribute=="quantity":
                orig_val_str=str(item.quantity); proc_val=float(value)
                if proc_val<=0: await interaction.followup.send("**Мастер:** Кол-во > 0.",ephemeral=True); return
                payload[attribute]=proc_val
            elif attribute in ["owner_id","owner_type","location_id"]:
                orig_val_str=str(getattr(item,attribute,"N/A")); proc_val=value if value.lower()!="none" else None; payload[attribute]=proc_val
                if attribute=="owner_id": payload["location_id"]=None; payload["owner_type"]=payload.get("owner_type") if proc_val else None
                elif attribute=="location_id" and proc_val: payload.update({"owner_id":None,"owner_type":None})
            else: await interaction.followup.send(f"**Мастер:** Атрибут '{attribute}' не поддерживается.",ephemeral=True); return
            if not payload: await interaction.followup.send(f"**Мастер:** Нечего обновлять для '{attribute}'.",ephemeral=True); return
            if await gm.item_manager.update_item_instance(gid,item_instance_id,payload):
                gm.item_manager.mark_item_dirty(gid,item_instance_id)
                log_d={"item_id":item_instance_id,"item_name":item_tpl_name,"attr":attribute,"old":orig_val_str,"new":str(proc_val),"gm_id":str(interaction.user.id),"gm_name":interaction.user.name}
                await gm.game_log_manager.log_event(gid,"gm_edit_item",details=log_d)
                await interaction.followup.send(f"**Мастер:** Предмет '{item_tpl_name}' (`{item_instance_id}`) обновлен: '{attribute}' с '{orig_val_str}' на '{str(proc_val)}'.",ephemeral=True)
            else: await interaction.followup.send(f"**Мастер:** Ошибка обновления '{item_instance_id}'.",ephemeral=True)
        except Exception as e: traceback.print_exc(); await interaction.followup.send(f"**Мастер:** Ошибка: {e}",ephemeral=True)

    @app_commands.command(name="master_create_item", description="ГМ: Создать новый экземпляр предмета.")
    @app_commands.describe(template_id="ID шаблона.", target_id="Опц: ID владельца/локации.", target_type="Опц: Тип цели ('character', 'npc', 'location').", quantity="Опц: Количество (default 1).")
    async def cmd_master_create_item(self, interaction: Interaction, template_id: str, target_id: Optional[str]=None, target_type: Optional[str]=None, quantity: Optional[float]=1.0):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.",ephemeral=True); return
        await interaction.response.defer(ephemeral=True,thinking=True)
        gid,gm=str(interaction.guild_id),self.bot.game_manager
        if not gm or not all(hasattr(gm,m) and getattr(gm,m) for m in ['item_manager','game_log_manager','character_manager','npc_manager','location_manager']):
            await interaction.followup.send("**Мастер:** Один из менеджеров недоступен.",ephemeral=True); return
        qty=quantity if quantity is not None else 1.0
        if qty<=0: await interaction.followup.send("**Мастер:** Кол-во >0.",ephemeral=True); return
        if not (item_tpl:=gm.item_manager.get_item_template(template_id)): await interaction.followup.send(f"**Мастер:** Шаблон '{template_id}' не найден.",ephemeral=True); return
        tpl_name_log=item_tpl.get("name_i18n",{}).get("en",template_id); own_id,own_type,loc_id=None,None,None
        if target_id:
            if not target_type: await interaction.followup.send("**Мастер:** 'target_type' обязателен.",ephemeral=True); return
            tt=target_type.lower()
            if tt in ["character","player"]:
                char=gm.character_manager.get_character_by_discord_id(gid,int(target_id)) if target_id.isdigit() else gm.character_manager.get_character(gid,target_id)
                if not char: await interaction.followup.send(f"**Мастер:** Персонаж '{target_id}' не найден.",ephemeral=True); return
                own_id,own_type=char.id,"Character"
            elif tt=="npc":
                if not (npc:=gm.npc_manager.get_npc(gid,target_id)): await interaction.followup.send(f"**Мастер:** NPC '{target_id}' не найден.",ephemeral=True); return
                own_id,own_type=npc.id,"NPC"
            elif tt=="location":
                # Assuming LocationManager.get_location_instance for consistency, or get_location_by_id if that's the actual method
                loc_obj = gm.location_manager.get_location_instance(gid, target_id) # Changed from get_location_by_id
                if not loc_obj: await interaction.followup.send(f"**Мастер:** Локация '{target_id}' не найдена.",ephemeral=True); return
                loc_id=loc_obj.id
            else: await interaction.followup.send("**Мастер:** Неверный 'target_type'.",ephemeral=True); return
        try:
            if new_item:=await gm.item_manager.create_item_instance(gid,template_id,own_id,own_type,loc_id,qty):
                log_d={"item_id":new_item.id,"tpl_id":template_id,"tpl_name":tpl_name_log,"qty":qty,"owner":own_id,"owner_t":own_type,"loc":loc_id,"gm_id":str(interaction.user.id),"gm_name":interaction.user.name}
                await gm.game_log_manager.log_event(gid,"gm_create_item",details=log_d)
                msg=f"**Мастер:** Предмет '{tpl_name_log}' (ID: {new_item.id}) x{qty} создан."
                if own_id: msg+=f" Владелец: {own_type} {own_id}."
                elif loc_id: msg+=f" В локации {loc_id}."
                await interaction.followup.send(msg,ephemeral=True)
            else: await interaction.followup.send(f"**Мастер:** Ошибка создания '{template_id}'.",ephemeral=True)
        except Exception as e: traceback.print_exc(); await interaction.followup.send(f"**Мастер:** Ошибка: {e}",ephemeral=True)

    @app_commands.command(name="master_launch_event", description="ГМ: Запустить событие по шаблону.")
    @app_commands.describe(template_id="ID шаблона.",location_id="Опц: ID локации.",channel_id="Опц: ID канала.",player_ids_json="Опц: JSON массив ID игроков.")
    async def cmd_master_launch_event(self, interaction: Interaction, template_id:str, location_id:Optional[str]=None, channel_id:Optional[str]=None, player_ids_json:Optional[str]=None):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.",ephemeral=True); return
        await interaction.response.defer(ephemeral=True,thinking=True)
        gid,gm=str(interaction.guild_id),self.bot.game_manager
        if not gm or not gm.event_manager or not gm.game_log_manager: await interaction.followup.send("**Мастер:** EventManager/GameLogManager недоступен.",ephemeral=True); return
        if not (evt_tpl:=gm.event_manager.get_event_template(gid,template_id)): await interaction.followup.send(f"**Мастер:** Шаблон '{template_id}' не найден.",ephemeral=True); return
        tpl_name_log=evt_tpl.get("name",template_id); p_ids:Optional[List[str]]=None
        if player_ids_json:
            try: p_ids=json.loads(player_ids_json)
            except: await interaction.followup.send("**Мастер:** Ошибка JSON 'player_ids_json'.",ephemeral=True); return
            if not isinstance(p_ids,list) or not all(isinstance(p,str) for p in p_ids): await interaction.followup.send("**Мастер:** 'player_ids_json' должен быть массивом строк.",ephemeral=True); return
        p_chan_id:Optional[int]=None
        if channel_id:
            try: p_chan_id=int(channel_id)
            except: await interaction.followup.send("**Мастер:** 'channel_id' должен быть числом.",ephemeral=True); return
        try:
            if created_evt:=await gm.event_manager.create_event_from_template(gid,template_id,location_id,p_ids,p_chan_id):
                log_d={"evt_id":created_evt.id,"tpl_id":template_id,"tpl_name":tpl_name_log,"loc":location_id,"chan":p_chan_id,"p_ids":p_ids,"gm_id":str(interaction.user.id),"gm_name":interaction.user.name}
                await gm.game_log_manager.log_event(gid,"gm_launch_event",details=log_d)
                evt_n=getattr(created_evt,'name',tpl_name_log)
                await interaction.followup.send(f"**Мастер:** Событие '{evt_n}' (ID:{created_evt.id}) запущено из '{template_id}'.",ephemeral=True)
            else: await interaction.followup.send(f"**Мастер:** Ошибка запуска '{template_id}'.",ephemeral=True)
        except Exception as e: traceback.print_exc(); await interaction.followup.send(f"**Мастер:** Ошибка: {e}",ephemeral=True)

    @app_commands.command(name="master_set_rule", description="ГМ: Установить значение для правила игры.")
    @app_commands.describe(rule_key="Путь к правилу (e.g., economy_rules.multiplier).",value_json="JSON значение.")
    async def cmd_master_set_rule(self, interaction: Interaction, rule_key: str, value_json: str):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.",ephemeral=True); return
        await interaction.response.defer(ephemeral=True,thinking=True)
        gid,gm,db=str(interaction.guild_id),self.bot.game_manager,self.bot.db_service
        if not db or not db.adapter: await interaction.followup.send("**Мастер:** DBService недоступен.",ephemeral=True); return
        if not gm or not gm.game_log_manager: await interaction.followup.send("**Мастер:** GameLogManager недоступен.",ephemeral=True); return
        from bot.api.schemas.rule_config_schemas import RuleConfigData
        try:
            row=await db.adapter.fetchone("SELECT config_data FROM rules_config WHERE guild_id=$1",(gid,)); cfg_dict:Dict[str,Any]; new_cfg=False
            if row and row['config_data']: cfg_dict=row['config_data'] if isinstance(row['config_data'],dict) else json.loads(str(row['config_data']))
            else: new_cfg=True; cfg_dict=RuleConfigData().model_dump()
            try: new_val=json.loads(value_json)
            except json.JSONDecodeError: await interaction.followup.send(f"**Мастер:** Ошибка JSON: `{value_json}`.",ephemeral=True); return
            keys,curr_lvl,orig_val=rule_key.split('.'),cfg_dict,None
            for i,k_part in enumerate(keys[:-1]):
                if not isinstance(curr_lvl,dict) or k_part not in curr_lvl: await interaction.followup.send(f"**Мастер:** Неверный путь '{rule_key}', '{k_part}' не найден/не словарь.",ephemeral=True); return
                curr_lvl=curr_lvl[k_part]
            f_key=keys[-1]
            if not isinstance(curr_lvl,dict): await interaction.followup.send(f"**Мастер:** Неверный путь '{rule_key}', '{keys[-2] if len(keys)>1 else '<корень>'}' не словарь для '{f_key}'.",ephemeral=True); return
            proc_val=new_val
            if f_key in curr_lvl:
                orig_val=curr_lvl[f_key]
                if orig_val is not None:
                    try:
                        tgt_type=type(orig_val)
                        if tgt_type==bool and isinstance(new_val,str):new_val=True if new_val.lower()=='true' else (False if new_val.lower()=='false' else "INVALID_BOOL")
                        proc_val=tgt_type(new_val)
                    except (ValueError,TypeError) as e: await interaction.followup.send(f"**Мастер:** Ошибка типа для '{f_key}'. Ожидался {tgt_type.__name__}, получен '{value_json}'. {e}",ephemeral=True); return
            curr_lvl[f_key]=proc_val; orig_val_str=str(orig_val) if orig_val is not None else "N/A (новый ключ)"
            if new_cfg: await db.adapter.execute("INSERT INTO rules_config (guild_id,config_data) VALUES ($1,$2)",(gid,json.dumps(cfg_dict)))
            else: await db.adapter.execute("UPDATE rules_config SET config_data=$1 WHERE guild_id=$2",(json.dumps(cfg_dict),gid))
            if hasattr(gm,'rule_engine') and hasattr(gm.rule_engine,'load_rules_config_for_guild'):
                try: await gm.rule_engine.load_rules_config_for_guild(gid)
                except Exception as e_rl: print(f"Error reloading RuleEngine for {gid}: {e_rl}")
            log_d={"gid":gid,"key":rule_key,"old":orig_val_str,"new_json":value_json,"new_val":proc_val,"gm_id":str(interaction.user.id),"gm_name":interaction.user.name}
            await gm.game_log_manager.log_event(gid,"gm_set_rule",details=log_d)
            await interaction.followup.send(f"**Мастер:** Правило '{rule_key}' установлено на '{value_json}'.",ephemeral=True)
        except Exception as e: traceback.print_exc(); await interaction.followup.send(f"**Мастер:** Ошибка: {e}",ephemeral=True)

    # --- Simulation Commands ---
    # SimpleReportFormatter class removed from here, will be imported from bot.game.services.report_formatter

    @app_commands.command(name="run_simulation", description="ГМ: Запустить симуляцию (бой, квест, последствия).")
    @app_commands.choices(simulation_type=[app_commands.Choice(name="Battle",value="battle"), app_commands.Choice(name="Quest",value="quest"), app_commands.Choice(name="Action Consequence",value="action_consequence")])
    @app_commands.describe(simulation_type="Тип симуляции.", params_json="JSON параметры.")
    async def cmd_run_simulation(self, interaction: Interaction, simulation_type: app_commands.Choice[str], params_json: str):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True, thinking=True); gid, gm = str(interaction.guild_id), self.bot.game_manager
        if not gm: await interaction.followup.send("**Мастер:** GameManager недоступен.", ephemeral=True); return

        from bot.game.services.report_formatter import SimpleReportFormatter # Updated import

        req_mgrs = ['character_manager','npc_manager','rule_engine','game_log_manager','item_manager','event_manager','combat_manager','relationship_manager','location_manager']
        if simulation_type.value=="quest" and (not hasattr(gm,'quest_manager') or not gm.quest_manager): print(f"Warn: QuestManager missing for quest sim {gid}.")
        if any(not hasattr(gm,m) or getattr(gm,m) is None for m in req_mgrs): await interaction.followup.send("**Мастер:** Один из менеджеров недоступен.", ephemeral=True); return

        import uuid; from bot.game.simulation import BattleSimulator,QuestSimulator,ActionConsequenceModeler

        try: params = json.loads(params_json)
        except json.JSONDecodeError: await interaction.followup.send("**Мастер:** Ошибка JSON.", ephemeral=True); return

        report, fmt, rep_id, lang = None, SimpleReportFormatter(gm,gid), str(uuid.uuid4()), str(interaction.locale or "en") # Instantiation remains the same
        fmtd_report = ""
        try:
            if simulation_type.value=="battle":
                sim=BattleSimulator(gid,gm.character_manager,gm.npc_manager,gm.combat_manager,gm.rule_engine,gm.item_manager)
                report=await sim.simulate_full_battle(params.get('participants_setup',[]),params.get('rules_config_override_data'),params.get('max_rounds',50))
                fmtd_report=fmt.format_battle_report(report,lang)
            elif simulation_type.value=="quest":
                qdefs=getattr(gm.quest_manager,'get_all_quest_definitions',lambda g:{})(gid) if hasattr(gm,'quest_manager') and gm.quest_manager else {}
                if not qdefs and not params.get('quest_definitions_override'): await interaction.followup.send("**Мастер:** Определения квестов не найдены.",ephemeral=True); return
                sim=QuestSimulator(gid,gm.character_manager,gm.event_manager,gm.rule_engine,params.get('quest_definitions_override',qdefs))
                report=await sim.simulate_full_quest(params.get('quest_id',''),params.get('character_ids',[]),params.get('rules_config_override_data'),params.get('max_stages',20))
                fmtd_report=fmt.format_quest_report(report,lang)
            elif simulation_type.value=="action_consequence":
                sim=ActionConsequenceModeler(gid,gm.character_manager,gm.npc_manager,gm.rule_engine,gm.relationship_manager,gm.event_manager)
                report=await sim.analyze_action_consequences(params.get('action_description',{}),params.get('actor_id',''),params.get('actor_type',''),params.get('target_id'),params.get('target_type'),params.get('rules_config_override_data'))
                fmtd_report=fmt.format_action_consequence_report(report,lang)
            else: await interaction.followup.send(f"**Мастер:** Неизвестный тип '{simulation_type.value}'.",ephemeral=True); return
            if report:
                await gm.game_log_manager.log_event(gid,"gm_simulation_report",{"report_id":rep_id,"type":simulation_type.value,"params":params_json,"report":report})
                msg=f"Симуляция '{simulation_type.name}' завершена. ID: `{rep_id}`\n\n{fmtd_report}"
                await interaction.followup.send(msg[:1950]+("..." if len(msg)>1950 else ""),ephemeral=True)
            else: await interaction.followup.send(f"**Мастер:** Симуляция '{simulation_type.name}' не дала данных.",ephemeral=True)
        except Exception as e: traceback.print_exc(); await interaction.followup.send(f"**Мастер:** Ошибка симуляции '{simulation_type.name}': {e}",ephemeral=True)

    @app_commands.command(name="view_simulation_report",description="ГМ: Просмотреть отчет симуляции.")
    @app_commands.describe(report_id="ID отчета.")
    async def cmd_view_simulation_report(self, interaction: Interaction, report_id: str): # Renamed interaction to 'interaction'
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.",ephemeral=True); return
        await interaction.response.defer(ephemeral=True,thinking=True); gid,gm=str(interaction.guild_id),self.bot.game_manager
        if not gm or not gm.game_log_manager: await interaction.followup.send("**Мастер:** GameLogManager недоступен.",ephemeral=True); return
        try:
            logs=await gm.game_log_manager.get_logs_by_guild(gid,limit=500,event_type_filter="gm_simulation_report")
            entry_data:Optional[Dict[str,Any]]=None
            for log_row in logs:
                details=log_row.get('details'); details=json.loads(details) if isinstance(details,str) else details
                if isinstance(details,dict) and details.get('report_id')==report_id: entry_data=details; break
            if entry_data and 'report_data' in entry_data and 'simulation_type' in entry_data:
                report_data,sim_type_from_log,lang=entry_data['report_data'],entry_data['simulation_type'],str(interaction.locale or "en")

                from bot.game.services.report_formatter import SimpleReportFormatter # Updated import
                fmt=SimpleReportFormatter(gm,gid)

                if not isinstance(report_data, (dict, list)):
                    try: report_data = json.loads(str(report_data))
                    except json.JSONDecodeError: await interaction.followup.send(f"**Мастер:** Ошибка: данные отчета для ID '{report_id}' повреждены.", ephemeral=True); return

                formatter_method_name = f"format_{sim_type_from_log}_report"
                if hasattr(fmt, formatter_method_name):
                    formatter_method = getattr(fmt, formatter_method_name)
                    fmtd_report = formatter_method(report_data, lang)
                else:
                    fmtd_report = fmt.format_generic_report(report_data, lang)

                msg=f"**Отчет (ID: {report_id}, Тип: {sim_type_from_log})**:\n\n{fmtd_report}"
                await interaction.followup.send(msg[:1950]+("..." if len(msg)>1950 else ""),ephemeral=True)
            else: await interaction.followup.send(f"**Мастер:** Отчет ID '{report_id}' не найден.",ephemeral=True)
        except Exception as e: traceback.print_exc(); await interaction.followup.send(f"**Мастер:** Ошибка просмотра: {e}",ephemeral=True)

    @app_commands.command(name="compare_reports",description="ГМ: Сравнить два отчета (концепт).")
    @app_commands.describe(report_id_1="ID первого отчета.",report_id_2="ID второго отчета.")
    async def cmd_compare_reports(self, interaction:Interaction, report_id_1:str, report_id_2:str): # Renamed interaction
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.",ephemeral=True); return
        await interaction.response.defer(ephemeral=True,thinking=True)
        await interaction.followup.send(f"**Мастер:** Сравнение '{report_id_1}' и '{report_id_2}'. Функция в разработке.",ephemeral=True)

    @app_commands.command(name="master_view_npcs", description="ГМ: Просмотреть NPC (фильтр по локации).")
    @app_commands.describe(location_id_filter="Опц: ID локации.")
    async def cmd_master_view_npcs(self, interaction: Interaction, location_id_filter: Optional[str]=None):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.",ephemeral=True); return
        await interaction.response.defer(ephemeral=True,thinking=True)
        gid,gm,lang = str(interaction.guild_id),self.bot.game_manager,str(interaction.locale or "en")
        if not gm or not gm.npc_manager or not gm.location_manager: await interaction.followup.send("**Мастер:** NPC/Location Manager недоступен.",ephemeral=True); return
        from bot.game.models.npc import NPC as NPCModelType # For type hint
        npc_list: List[NPCModelType] = []; header = "" # Ensure npc_list is typed
        if location_id_filter:
            loc = gm.location_manager.get_location_instance(gid, location_id_filter)
            if not loc: await interaction.followup.send(f"**Мастер:** Локация '{location_id_filter}' не найдена.",ephemeral=True); return
            loc_name = (loc.name_i18n.get(lang,loc.name_i18n.get("en",loc.id)) if hasattr(loc,"name_i18n") and loc.name_i18n else getattr(loc,"name",loc.id))
            header = f"**NPC в локации '{loc_name}' (`{location_id_filter}`)**:\n"
            npc_list = gm.npc_manager.get_npcs_in_location(gid, location_id_filter)
        else: header = "**Все NPC в гильдии**:\n"; npc_list = gm.npc_manager.get_all_npcs(gid)
        if not npc_list: await interaction.followup.send(f"**Мастер:** NPC не найдены {(f'в `{location_id_filter}`' if location_id_filter else 'в гильдии')}.",ephemeral=True); return
        lines:List[str]=[]
        for npc in npc_list: # npc is NPCModelType
            npc_name = npc.name_i18n.get(lang,npc.name_i18n.get("en",npc.id)) if hasattr(npc,"name_i18n") and npc.name_i18n else getattr(npc,"name",npc.id)
            loc_str="N/A"
            if npc.location_id and (loc_inst:=gm.location_manager.get_location_instance(gid,npc.location_id)):
                loc_n=(loc_inst.name_i18n.get(lang,loc_inst.name_i18n.get("en",loc_inst.id)) if hasattr(loc_inst,"name_i18n") and loc_inst.name_i18n else getattr(loc_inst,"name",loc_inst.id))
                loc_str=f"{loc_n} (`{npc.location_id}`)"
            elif npc.location_id: loc_str=f"Unknown (`{npc.location_id}`)"
            lines.append(f"- ID:`{npc.id}` Имя:**{npc_name}** Лок:{loc_str} HP:{getattr(npc,'hp','N/A')}/{getattr(npc,'max_health','N/A')}")
        msgs,cur_msg=[],header
        for ln in lines:
            if len(cur_msg)+len(ln)+1>1950: msgs.append(cur_msg); cur_msg="" # Start new message part without header
            cur_msg+=("\n" if cur_msg else "")+ln
        if cur_msg: msgs.append(cur_msg) # Add any remaining part
        if not msgs: await interaction.followup.send("**Мастер:** Не удалось сформировать список.",ephemeral=True); return

        first_message_sent = False
        for i,part_msg in enumerate(msgs):
            final_msg_part = part_msg
            if i == 0 and not part_msg.startswith(header): # If header was too long and split
                 final_msg_part = header + part_msg

            page_prefix = f"(Часть {i+1}/{len(msgs)})\n" if len(msgs) > 1 else ""
            if i == 0 : # First message, potentially with header
                 await interaction.followup.send(f"{page_prefix if len(msgs)>1 else ''}{final_msg_part}",ephemeral=True)
            else: # Subsequent messages
                 await interaction.followup.send(f"{page_prefix}{final_msg_part}",ephemeral=True)
            first_message_sent = True
        if not first_message_sent and header.strip(): # Case where only header exists and it's short
            await interaction.followup.send(header, ephemeral=True)


    @app_commands.command(name="master_view_log", description="ГМ: Просмотреть логи событий сервера.")
    @app_commands.describe(event_type_filter="Опц: Фильтр по типу события.", limit="Опц: Кол-во записей (1-200, default 50).")
    async def cmd_master_view_log(self, interaction: Interaction, event_type_filter: Optional[str]=None, limit:app_commands.Range[int,1,200]=50): # type: ignore
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.",ephemeral=True); return
        await interaction.response.defer(ephemeral=True,thinking=True); guild_id_str,game_mngr=str(interaction.guild_id),self.bot.game_manager
        if not game_mngr or not game_mngr.game_log_manager: await interaction.followup.send("**Мастер:** GameLogManager недоступен.",ephemeral=True); return
        try: from bot.game.services.report_formatter import ReportFormatter
        except ImportError: await interaction.followup.send("**Мастер:** ReportFormatter не найден.",ephemeral=True); return
        if not all(hasattr(game_mngr,m) and getattr(game_mngr,m) for m in ['character_manager','npc_manager','item_manager']):
            await interaction.followup.send("**Мастер:** Менеджеры для ReportFormatter недоступны.",ephemeral=True); return
        fmt=ReportFormatter(game_mngr.character_manager,game_mngr.npc_manager,game_mngr.item_manager)
        try:
            logs=await game_mngr.game_log_manager.get_logs_by_guild(guild_id_str,limit=(limit or 50),event_type_filter=event_type_filter)
            if not logs: await interaction.followup.send(f"**Мастер:** Логи не найдены (фильтр: '{event_type_filter or 'Нет'}').",ephemeral=True); return
            lang,lines=str(interaction.locale or "en"),[]
            from datetime import timezone
            for entry in logs:
                if 'guild_id' not in entry: entry['guild_id']=guild_id_str
                ts = entry.get('timestamp'); ts_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z") if ts else 'N/A'
                et_str=str(entry.get('event_type','N/A'))
                try:
                    desc=await fmt.format_story_log_entry(entry,lang)
                    dtls,preview=entry.get('details'),""
                    if dtls:
                        if isinstance(dtls,str): dtls=json.loads(dtls) if dtls.startswith('{') or dtls.startswith('[') else {}
                        if isinstance(dtls,dict): preview=f" (...{', '.join([f'{k}: {v}' for k,v in list(dtls.items())[:2]])}...)"
                    lines.append(f"`{ts_str}` `[{et_str}]` {desc}{preview}")
                except Exception as e_fmt: lines.append(f"`{ts_str}` `[{et_str}]` Error log format {entry.get('id')}: {e_fmt}")
            msgs,cur_msg= [], ""
            hdr = f"**Игровой лог ({len(lines)} записей)**:\n"
            for i,ln in enumerate(lines):
                line_to_add = (hdr if i == 0 else "") + ln
                if len(cur_msg) + len(line_to_add) + (1 if cur_msg and i > 0 else 0) > 1950:
                    msgs.append(cur_msg)
                    cur_msg = (hdr if i == 0 and len(msgs) > 0 else "") + ln # Start new part, add header if it's a new first part
                else:
                    cur_msg += ("\n" if cur_msg and not cur_msg.endswith(hdr) else "") + ln
            if cur_msg: msgs.append(cur_msg)
            if not msgs: await interaction.followup.send("**Мастер:** Не удалось сформировать логи.",ephemeral=True); return
            for i,part in enumerate(msgs):
                final_msg = f"(Часть {i+1}/{len(msgs)})\n{part}" if len(msgs) > 1 else part
                if i==0 and not final_msg.startswith(hdr): final_msg = hdr + final_msg # Ensure first message has header
                await interaction.followup.send(final_msg,ephemeral=True)
        except Exception as e: traceback.print_exc(); await interaction.followup.send(f"**Мастер:** Ошибка просмотра: {e}",ephemeral=True)

    @app_commands.command(name="master_view_player_stats", description="ГМ: Просмотреть статы и информацию об игроке.")
    @app_commands.describe(character_id="ID персонажа или Discord ID игрока.")
    async def cmd_master_view_player_stats(self, interaction: Interaction, character_id: str):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.",ephemeral=True); return
        await interaction.response.defer(ephemeral=True,thinking=True); guild_id_str,game_mngr = str(interaction.guild_id),self.bot.game_manager
        if not game_mngr or not game_mngr.character_manager or not game_mngr.location_manager: await interaction.followup.send("**Мастер:** Character/LocationManager недоступен.",ephemeral=True); return
        char = game_mngr.character_manager.get_character(guild_id_str,character_id) if not character_id.isdigit() else game_mngr.character_manager.get_character_by_discord_id(guild_id_str,int(character_id))
        if not char and character_id.isdigit(): char = game_mngr.character_manager.get_character(guild_id_str, character_id)
        if not char: await interaction.followup.send(f"**Мастер:** Персонаж '{character_id}' не найден.",ephemeral=True); return
        lang = str(interaction.locale or "en")
        char_name = (char.name_i18n.get(lang,char.name_i18n.get("en",char.id)) if hasattr(char,"name_i18n") and char.name_i18n else getattr(char,"name",char.id))
        details=[f"**Информация о персонаже: {char_name}**", f"- ID Персонажа: `{char.id}`", f"- Discord User ID: `{char.discord_user_id}`",
                   f"- Уровень: {char.level}", f"- Опыт: {char.experience}", f"- Непотраченный опыт: {char.unspent_xp}", # Corrected xp attribute
                   f"- HP: {char.hp} / {char.max_health}"]
        cl_name=char.character_class;_i18n=getattr(char,'class_i18n',{}); cl_name=_i18n.get(lang,_i18n.get("en",cl_name)) if isinstance(_i18n,dict) and _i18n else cl_name
        details.append(f"- Класс: {cl_name or 'N/A'}"); details.append(f"- Выбранный язык: {char.selected_language}")
        loc_str="N/A"
        # Corrected attribute access for location_id on char model
        char_loc_id = getattr(char, 'location_id', None) or getattr(char, 'current_location_id', None)
        if char_loc_id and (loc_inst:=game_mngr.location_manager.get_location_instance(guild_id_str,char_loc_id)):
            loc_n=(loc_inst.name_i18n.get(lang,loc_inst.name_i18n.get("en",loc_inst.id)) if hasattr(loc_inst,"name_i18n") and loc_inst.name_i18n else getattr(loc_inst,"name",loc_inst.id))
            loc_str=f"{loc_n} (`{char_loc_id}`)"
        elif char_loc_id: loc_str=f"Unknown (`{char_loc_id}`)"
        details.append(f"- Текущая локация: {loc_str}")
        if char.stats: details.extend(["\n**Базовые статы:**"]+[f"  - {s.replace('_',' ').capitalize()}: {v}" for s,v in char.stats.items()])
        if eff_s:=getattr(char,'effective_stats_json',None):
            try:
                if isinstance(eff_s, str) and (eff_d:=json.loads(eff_s)): details.extend(["\n**Эффективные статы:**"]+[f"  - {s.replace('_',' ').capitalize()}: {v}" for s,v in eff_d.items()])
                elif isinstance(eff_s, dict) and eff_s: details.extend(["\n**Эффективные статы:**"]+[f"  - {s.replace('_',' ').capitalize()}: {v}" for s,v in eff_s.items()])
            except json.JSONDecodeError: details.append("\n- Эффективные статы: (ошибка JSON)")
        msg="\n".join(details); await interaction.followup.send(msg[:1950]+("..." if len(msg)>1950 else ""),ephemeral=True)

    @app_commands.command(name="master_view_map", description="ГМ: Просмотреть карту или детали локации.")
    @app_commands.describe(location_id="Опционально: ID локации для просмотра деталей.")
    async def cmd_master_view_map(self, interaction: Interaction, location_id: Optional[str] = None):
        if not await is_master_or_admin_check(interaction): await interaction.response.send_message("**Мастер:** Нет прав.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True, thinking=True)
        gid, gm, lang = str(interaction.guild_id), self.bot.game_manager, str(interaction.locale or "en")
        if not gm or not all(hasattr(gm,m) and getattr(gm,m) for m in ['location_manager','npc_manager','character_manager','event_manager']):
            await interaction.followup.send("**Мастер:** Один или несколько менеджеров недоступны.", ephemeral=True); return

        fmt = self.SimpleReportFormatter(gm, gid)
        if location_id is None:
            all_loc_data = []
            if hasattr(gm.location_manager, 'get_all_location_instances'): # Prefer method returning models
                 all_loc_data = gm.location_manager.get_all_location_instances(gid)
            elif hasattr(gm.location_manager, '_location_instances'): # Fallback for older LocationManager
                 all_loc_data = [gm.location_manager.get_location_instance(gid, loc_id) for loc_id in gm.location_manager._location_instances.get(gid, {}).keys()]
                 all_loc_data = [loc for loc in all_loc_data if loc]

            if not all_loc_data: await interaction.followup.send("**Мастер:** Локаций не найдено.", ephemeral=True); return
            lines = ["**Все локации в гильдии:**"]
            for loc_obj in all_loc_data:
                loc_name = getattr(loc_obj,"name_i18n",{}).get(lang, getattr(loc_obj,"name_i18n",{}).get("en", loc_obj.id)) if hasattr(loc_obj,"name_i18n") else getattr(loc_obj,"name", loc_obj.id)
                lines.append(f"- `{loc_obj.id}`: **{loc_name}**")
            msgs,cur_msg,hdr="",lines.pop(0)+"\n",""
            cur_msg = hdr
            for ln in lines:
                if len(cur_msg)+len(ln)+1 > 1950: msgs.append(cur_msg); cur_msg = ""
                cur_msg += ("\n" if cur_msg else "") + ln
            if cur_msg: msgs.append(cur_msg)
            for i,part in enumerate(msgs): await interaction.followup.send(f"{'(Часть '+str(i+1)+'/'+str(len(msgs))+')\n' if len(msgs)>1 and i>0 else ''}{part if i==0 and part.startswith(hdr) else (hdr if i==0 else '')+part }",ephemeral=True)
        else:
            loc = gm.location_manager.get_location_instance(gid, location_id)
            if not loc: await interaction.followup.send(f"**Мастер:** Локация `{location_id}` не найдена.", ephemeral=True); return
            loc_name = loc.name_i18n.get(lang, loc.name_i18n.get("en", loc.id)) if hasattr(loc,"name_i18n") and loc.name_i18n else getattr(loc,"name",loc.id)
            loc_desc = getattr(loc, "display_description", loc.descriptions_i18n.get(lang, loc.descriptions_i18n.get("en","N/A")))
            details = [f"**Детали локации: {loc_name} (`{loc.id}`)**", f"Описание: {loc_desc}"]
            if hasattr(loc,'exits') and loc.exits and isinstance(loc.exits,dict):
                ex_lns = ["\n**Выходы:**"] + [f"- {d.capitalize()}: {fmt._get_entity_name(str(tid.get('target_location_id') if isinstance(tid,dict) else tid), 'location', lang)}" for d,tid in loc.exits.items()]
                details.extend(ex_lns if len(ex_lns)>1 else ["- Выходов нет."])
            else: details.append("\n**Выходы:** Информации нет.")
            if npcs:=gm.npc_manager.get_npcs_in_location(gid,loc.id): details.extend(["\n**NPC:**"]+[f"- {fmt._get_entity_name(n.id,'npc',lang)}" for n in npcs])
            if chars:=gm.character_manager.get_characters_in_location(gid,loc.id): details.extend(["\n**Персонажи:**"]+[f"- {fmt._get_entity_name(c.id,'character',lang)} (Discord: <@{c.discord_user_id}>)" for c in chars])
            if hasattr(gm, 'event_manager') and (active_evts:=gm.event_manager.get_active_events(gid)):
                loc_evts=[e for e in active_evts if (hasattr(e,'location_id') and e.location_id==loc.id) or (hasattr(e,'state_variables') and isinstance(e.state_variables,dict) and e.state_variables.get('linked_location_id')==loc.id)]
                if loc_evts: details.extend(["\n**События:**"]+[f"- {fmt._get_entity_name(evt.id,'event',lang)}" for evt in loc_evts])
            msg="\n".join(details); await interaction.followup.send(msg[:1950]+("..." if len(msg)>1950 else ""),ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(GMAppCog(bot)) # type: ignore
    print("GMAppCog loaded.")
    await bot.add_cog(GMAppCog(bot)) # type: ignore
    print("GMAppCog loaded.")

