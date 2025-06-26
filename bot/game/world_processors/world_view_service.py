# bot/game/world_processors/world_view_service.py

import traceback
import asyncio
from typing import Optional, Dict, Any, List, TYPE_CHECKING, cast


from bot.game.managers.location_manager import LocationManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.party_manager import PartyManager

from bot.services.openai_service import OpenAIService
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.status_manager import StatusManager


from bot.game.models.character import Character
from bot.game.models.npc import NPC
from bot.game.models.item import Item
from bot.game.models.party import Party
from bot.game.models.relationship import Relationship
from bot.game.models.quest import Quest


from bot.utils.i18n_utils import get_i18n_text

DEFAULT_BOT_LANGUAGE = "en"

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.quest_manager import QuestManager


class WorldViewService:
    def __init__(self,
                 location_manager: LocationManager,
                 character_manager: CharacterManager,
                 npc_manager: NpcManager,
                 item_manager: ItemManager,
                 party_manager: PartyManager,
                 openai_service: Optional[OpenAIService] = None,
                 rule_engine: Optional[RuleEngine] = None,
                 status_manager: Optional[StatusManager] = None,
                 db_service: Optional["DBService"] = None,
                 relationship_manager: Optional["RelationshipManager"] = None,
                 quest_manager: Optional["QuestManager"] = None,
                ):
        print("Initializing WorldViewService...")
        self._location_manager = location_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._party_manager = party_manager
        self._openai_service = openai_service
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._db_service = db_service
        self._relationship_manager = relationship_manager
        self._quest_manager = quest_manager
        print("WorldViewService initialized.")

    async def get_location_description(self,
                                       guild_id: str,
                                       location_id: str,
                                       viewer_entity_id: str,
                                       viewer_entity_type: str,
                                       **kwargs
                                      ) -> Optional[str]:
        print(f"WorldViewService: Generating description for location {location_id} for viewer {viewer_entity_type} ID {viewer_entity_id} in guild {guild_id}.")
        player_lang = DEFAULT_BOT_LANGUAGE
        viewer_char_obj: Optional[Character] = None
        if viewer_entity_type == 'Character' and self._character_manager:
            char_result = await self._character_manager.get_character(guild_id, viewer_entity_id) # Added await
            if isinstance(char_result, Character): # Check type
                viewer_char_obj = char_result
                if viewer_char_obj and viewer_char_obj.selected_language:
                    player_lang = viewer_char_obj.selected_language

        print(f"WorldViewService: Using language '{player_lang}' for viewer {viewer_entity_id}.")
        world_state_description_parts = []
        if self._db_service:
            relevant_world_states = ["current_era", "sky_condition", "magical_aura", "presence_shadow_lord", "holy_aura_active_region_A"]
            world_state_consequences_i18n = {
                "eternal_night": {"description_i18n": {"en": "The land is cast in perpetual twilight.", "ru": "Земля погружена в вечные сумерки."}},
                "high_mana_flux": {"description_i18n": {"en": "The air crackles with raw magical energy.", "ru": "Воздух трещит от необузданной магической энергии."}},
                "celestial_alignment": {"description_i18n": {"en": "Mystical constellations align in the sky, empowering certain fates.", "ru": "Мистические созвездия выстраиваются в небе, усиливая определенные судьбы."}},
                "shadow_lord_active_in_region": {"description_i18n": {"en": "A chilling sense of dread permeates the area, hinting at a dark power's influence.", "ru": "Леденящее чувство ужаса пронизывает это место, намекая на влияние темной силы."}},
                "shadow_lord_dormant": {"description_i18n": {"en": "The oppressive shadow that once blanketed this land feels distant, almost forgotten.", "ru": "Угнетающая тень, некогда покрывавшая эту землю, кажется далекой, почти забытой."}},
                "holy_aura_strong_A": {"description_i18n": {"en": "A palpable holy aura blesses this area, offering peace and warding off lesser evils.", "ru": "Ощутимая святая аура благословляет это место, даруя мир и отгоняя меньшее зло."}}
            }
            for key in relevant_world_states:
                raw_value = await self._db_service.get_global_state_value(key) # Added await
                if raw_value:
                    consequence_data = world_state_consequences_i18n.get(raw_value)
                    if consequence_data:
                        consequence_desc = get_i18n_text(consequence_data, 'description_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id)
                        if consequence_desc and "not found" not in consequence_desc.lower() and consequence_desc != raw_value:
                            world_state_description_parts.append(consequence_desc)

        location_data_result = await self._location_manager.get_location_instance(guild_id, location_id) # Added await, changed to get_location_instance
        if not location_data_result:
            print(f"WorldViewService: Error generating location description: Location {location_id} not found.")
            return None

        location_data: Dict[str, Any] = {} # Ensure location_data is a dict
        if hasattr(location_data_result, 'to_dict') and callable(getattr(location_data_result, 'to_dict')) :
            location_data = location_data_result.to_dict() # Convert model to dict if possible
        elif isinstance(location_data_result, dict):
            location_data = location_data_result
        else: # Fallback if not a model with to_dict or a dict itself
            print(f"WorldViewService: Location data for {location_id} is not a dict or model with to_dict.")
            return None


        entities_in_location: List[Any] = []
        excluded_id = viewer_char_obj.id if viewer_char_obj else viewer_entity_id

        if self._character_manager:
            all_characters_result = await self._character_manager.get_characters_in_location(guild_id, location_id) # Added await
            for char_obj_any in all_characters_result:
                char_obj = cast(Character, char_obj_any) # Cast to Character
                if viewer_entity_type == 'Character' and viewer_char_obj and char_obj.id == viewer_char_obj.id:
                    continue
                if getattr(char_obj, 'current_location_id', None) == location_id: # Use current_location_id
                     entities_in_location.append(char_obj)

        if self._npc_manager:
            all_npcs_result = await self._npc_manager.get_npcs_in_location(guild_id, location_id) # Added await
            for npc_obj_any in all_npcs_result:
                npc_obj = cast(NPC, npc_obj_any) # Cast to NPC
                if viewer_entity_type == 'NPC' and npc_obj.id == viewer_entity_id:
                    continue
                if getattr(npc_obj, 'current_location_id', None) == location_id: # Use current_location_id
                     entities_in_location.append(npc_obj)

        if self._item_manager:
            # Assuming get_items_by_owner can also mean items in a location if owner_id is location_id and owner_type is "location"
            # Or, if there's a specific get_items_in_location method. For now, using get_items_by_owner with location_id.
            # This might need adjustment based on ItemManager's capabilities.
            items_in_loc_result = await self._item_manager.get_items_by_owner(guild_id, location_id, owner_type="location") # Added await and owner_type
            for item_any in items_in_loc_result:
                item = cast(Item, item_any) # Cast to Item
                entities_in_location.append(item)

        if self._party_manager:
            # Assuming PartyManager has a method to get parties by location
            # This is a placeholder; PartyManager might need a specific method like get_parties_in_location
            all_parties_result = await self._party_manager.get_all_parties_for_guild(guild_id) # Added await, changed method name
            for party_any in all_parties_result:
                party = cast(Party, party_any) # Cast to Party
                if getattr(party, 'current_location_id', None) == location_id:
                     entities_in_location.append(party)

        entities_to_list = entities_in_location
        location_name = get_i18n_text(location_data, 'name_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id)
        location_description_base = get_i18n_text(location_data, 'descriptions_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id)
        description_text = f"**{location_name}**\n"
        main_description_parts = [location_description_base]
        if world_state_description_parts: main_description_parts.extend(world_state_description_parts)

        location_details = get_i18n_text(location_data, 'details_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id)
        if location_details and "not found" not in location_details.lower() and location_details != "details_i18n": main_description_parts.append(location_details)
        location_atmosphere = get_i18n_text(location_data, 'atmosphere_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id)
        if location_atmosphere and "not found" not in location_atmosphere.lower() and location_atmosphere != "atmosphere_i18n": main_description_parts.append(location_atmosphere)
        location_features = get_i18n_text(location_data, 'features_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id)
        if location_features and "not found" not in location_features.lower() and location_features != "features_i18n": main_description_parts.append(location_features)

        description_text += "\n".join(filter(None, main_description_parts))
        if main_description_parts and any(part for part in main_description_parts if part != location_description_base or part): description_text += "\n"

        if entities_to_list:
            description_text += f"\n{get_i18n_text(None, 'you_see_here_label', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text='Вы видите здесь:')}\n"
            relationship_cues_i18n = {
                "enemy_hostile": {"text_i18n": {"en": " (glares at you with intense hostility)", "ru": " (смотрит на вас с явной враждебностью)"}},
                "enemy_wary": {"text_i18n": {"en": " (seems wary and distrustful of you)", "ru": " (кажется, относится к вам с подозрением и недоверием)"}},
                "neutral_default": {"text_i18n": {"en": "", "ru": ""}},
                "friend_nod": {"text_i18n": {"en": " (offers you a friendly nod)", "ru": " (дружелюбно кивает вам)"}},
                "friend_warm": {"text_i18n": {"en": " (greets you warmly)", "ru": " (тепло приветствует вас)"}},
            }
            for entity in entities_to_list:
                entity_name_i18n_dict = getattr(entity, 'name_i18n', None)
                entity_name = get_i18n_text(entity_name_i18n_dict if isinstance(entity_name_i18n_dict, dict) else None, 'name_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text=getattr(entity, 'name', 'Unknown Entity'))


                entity_type_display = "???"
                if isinstance(entity, Character): entity_type_display = get_i18n_text(None, "entity_type_character", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text="Персонаж")
                elif isinstance(entity, NPC): entity_type_display = get_i18n_text(None, "entity_type_npc", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text="NPC")
                elif isinstance(entity, Item): entity_type_display = get_i18n_text(None, "entity_type_item", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text="Предмет")
                elif isinstance(entity, Party): entity_type_display = get_i18n_text(None, "entity_type_party", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text="Партия")

                faction_display_string = ""; relationship_text_cue = ""
                if isinstance(entity, NPC) and self._relationship_manager and viewer_char_obj:
                    faction_data = getattr(entity, 'faction', None)
                    if faction_data and isinstance(faction_data, dict):
                        localized_faction_name = get_i18n_text(faction_data, 'name_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id)
                        if localized_faction_name and "not found" not in localized_faction_name.lower() and localized_faction_name != "name_i18n": faction_display_string = f", {localized_faction_name}"

                    viewer_relationships_result = await self._relationship_manager.get_relationships_for_entity(guild_id, viewer_char_obj.id) # Added await
                    viewer_relationships: List[Relationship] = viewer_relationships_result if viewer_relationships_result else []

                    target_npc_id = entity.id
                    relationship_with_npc: Optional[Relationship] = None
                    for rel in viewer_relationships:
                        if (rel.entity1_id == viewer_char_obj.id and rel.entity2_id == target_npc_id) or (rel.entity2_id == viewer_char_obj.id and rel.entity1_id == target_npc_id):
                            relationship_with_npc = rel; break
                    if relationship_with_npc:
                        cue_key = None
                        if relationship_with_npc.relationship_type == 'enemy': cue_key = "enemy_hostile" if relationship_with_npc.strength <= -70 else "enemy_wary"
                        elif relationship_with_npc.relationship_type == 'friend': cue_key = "friend_warm" if relationship_with_npc.strength >= 70 else "friend_nod"
                        elif relationship_with_npc.relationship_type == 'neutral': cue_key = "neutral_default"
                        if cue_key:
                            cue_data = relationship_cues_i18n.get(cue_key)
                            if cue_data:
                                localized_cue = get_i18n_text(cue_data, 'text_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id)
                                if localized_cue and "not found" not in localized_cue.lower() and localized_cue != cue_data.get('text_i18n', {}).get(DEFAULT_BOT_LANGUAGE, "text_i18n"): relationship_text_cue = localized_cue
                description_text += f"- {entity_name} ({entity_type_display}{faction_display_string}){relationship_text_cue}\n"

        if self._quest_manager and viewer_char_obj:
            active_quest_data_list_result = await self._quest_manager.list_quests_for_character(guild_id, viewer_char_obj.id) # Added await
            active_quest_data_list = active_quest_data_list_result if active_quest_data_list_result else []
            quest_status_text: str = "" # Initialize
            if active_quest_data_list:
                active_quests_label = get_i18n_text(None, "active_quests_label", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text="Active Quests")
                if entities_to_list or (not entities_to_list and (main_description_parts and any(part for part in main_description_parts if part != location_description_base or part))): description_text += "\n"
                description_text += f"{active_quests_label}:\n"
                for quest_data_item in active_quest_data_list:
                    quest_obj = Quest.from_dict(quest_data_item); quest_obj.selected_language = player_lang
                    quest_name = quest_obj.name
                    current_objective_desc = ""
                    current_stage_id = quest_data_item.get('current_stage_id')
                    if current_stage_id:
                        stage_title = quest_obj.get_stage_title(str(current_stage_id)) if hasattr(quest_obj, 'get_stage_title') else None
                        stage_desc = quest_obj.get_stage_description(str(current_stage_id)) if hasattr(quest_obj, 'get_stage_description') else None
                        if stage_title and stage_title != f"Stage {current_stage_id} Title": current_objective_desc = f"{stage_title}: {stage_desc}"
                        else: current_objective_desc = stage_desc if stage_desc else ""
                    if not current_objective_desc or "not found" in current_objective_desc.lower(): current_objective_desc = quest_obj.description
                    if quest_name and "not found" not in quest_name.lower():
                        if "not found" in current_objective_desc.lower() or not current_objective_desc.strip(): current_objective_desc = get_i18n_text(None, "objective_not_specified_label", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text="Objective details not specified.")
                        description_text += f"- {quest_name}: {current_objective_desc}\n"

        exits_data_val = location_data.get('exits', {})
        exits_data = exits_data_val if isinstance(exits_data_val, dict) else {}


        if exits_data:
            exits_label = get_i18n_text(None, 'exits_label', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text='Exits:')
            if (self._quest_manager and viewer_char_obj and active_quest_data_list) or entities_to_list or (main_description_parts and any(part for part in main_description_parts if part != location_description_base or part)): description_text += "\n"
            description_text += f"{exits_label}\n"
            sorted_exit_keys = sorted(exits_data.keys())
            for exit_key in sorted_exit_keys:
                exit_info = exits_data[exit_key]
                if not isinstance(exit_info, dict): continue # Skip if not a dict
                target_location_id_exit = exit_info.get('target_location_id')
                exit_display_name = get_i18n_text(exit_info, 'name_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text=exit_key.capitalize())

                target_location_static_data_res = await self._location_manager.get_location_instance(guild_id, str(target_location_id_exit)) if target_location_id_exit else None # Added await, ensure str
                target_location_static_data: Optional[Dict[str, Any]] = None
                if hasattr(target_location_static_data_res, 'to_dict') and callable(getattr(target_location_static_data_res, 'to_dict')):
                    target_location_static_data = target_location_static_data_res.to_dict()
                elif isinstance(target_location_static_data_res, dict):
                     target_location_static_data = target_location_static_data_res


                target_location_name_display = str(target_location_id_exit) if target_location_id_exit else "N/A" # Fallback ensures string
                if target_location_static_data:
                    target_location_name_display = get_i18n_text(target_location_static_data, 'name_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text=str(target_location_id_exit))
                description_text += f"- **{exit_display_name}** {get_i18n_text(None, 'leads_to_label', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text='ведет в')} '{target_location_name_display}'\n"
        else:
            description_text += f"\n{get_i18n_text(None, 'no_exits_label', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text='Выходов из этой локации нет.')}\n"

        print(f"WorldViewService: Location description generated for {location_id} in language {player_lang}.")
        return description_text

    async def get_entity_details(self,
                                 guild_id: str,
                                 entity_id: str,
                                 entity_type: str,
                                 viewer_entity_id: str,
                                 viewer_entity_type: str,
                                 **kwargs
                                ) -> Optional[str]:
        print(f"WorldViewService: Generating details for entity {entity_type} ID {entity_id} for viewer {viewer_entity_type} ID {viewer_entity_id} in guild {guild_id}.")
        player_lang = DEFAULT_BOT_LANGUAGE
        viewer_char_obj_details: Optional[Character] = None
        if viewer_entity_type == 'Character' and self._character_manager:
            char_res_details = await self._character_manager.get_character(guild_id, viewer_entity_id) # Added await
            if isinstance(char_res_details, Character): # Check type
                viewer_char_obj_details = char_res_details
                if viewer_char_obj_details and viewer_char_obj_details.selected_language:
                    player_lang = viewer_char_obj_details.selected_language
        print(f"WorldViewService: Using language '{player_lang}' for entity details {entity_id}.")

        entity: Optional[Any] = None; manager: Optional[Any] = None
        if entity_type == 'Character' and self._character_manager:
             char_entity_res = await self._character_manager.get_character(guild_id, entity_id) # Added await
             if isinstance(char_entity_res, Character): entity = char_entity_res # Check type
             manager = self._character_manager
        elif entity_type == 'NPC' and self._npc_manager:
             npc_entity_res = await self._npc_manager.get_npc(guild_id, entity_id) # Added guild_id, await
             if isinstance(npc_entity_res, NPC): entity = npc_entity_res # Check type
             manager = self._npc_manager
        elif entity_type == 'Item' and self._item_manager:
             item_entity_res = await self._item_manager.get_item_instance_by_id(guild_id, entity_id) # Added guild_id, await, changed method name
             if isinstance(item_entity_res, Item): entity = item_entity_res # Check type
             manager = self._item_manager
        elif entity_type == 'Party' and self._party_manager:
             party_entity_res = await self._party_manager.get_party(guild_id, entity_id) # Added guild_id, await
             if isinstance(party_entity_res, Party): entity = party_entity_res # Check type
             manager = self._party_manager

        if entity is None:
            print(f"WorldViewService: Error generating entity details: Entity {entity_type} ID {entity_id} not found in manager cache.")
            return None

        description_text = ""
        entity_data_for_i18n = entity
        if hasattr(entity, 'to_dict') and callable(getattr(entity, 'to_dict')):
            entity_data_for_i18n = entity.to_dict()

        entity_name_i18n_val = getattr(entity, 'name_i18n', None) # Get the i18n dict or name attribute
        entity_name_val = getattr(entity, 'name', 'Unknown Entity')

        if isinstance(entity_name_i18n_val, dict):
             entity_name = get_i18n_text(entity_name_i18n_val, 'name_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text=entity_name_val)
        elif isinstance(entity_name_val, str): # Fallback to direct name if name_i18n is not a dict
            entity_name = entity_name_val
        else: # Ultimate fallback
            entity_name = get_i18n_text(None, "unknown_entity_name", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id)


        entity_type_display_details = get_i18n_text(None, f"entity_type_{entity_type.lower()}", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id, default_text=entity_type)
        description_text += f"**{entity_name}** ({entity_type_display_details})\n"
        description_text += f"ID: {entity_id}\n"

        def _format_basic_entity_details_placeholder(entity_obj: Any, entity_type_str: str, lang: str, guild_id_for_i18n: str, observed_details_dict: Dict[str, Any]) -> str:
            details = ""
            type_label = get_i18n_text(None, "label_type", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Тип")
            name_label = get_i18n_text(None, "label_name", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Имя")
            health_label = get_i18n_text(None, "label_health", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Здоровье")
            alive_label = get_i18n_text(None, "label_alive", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Жив")
            yes_label = get_i18n_text(None, "label_yes", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Да")
            no_label = get_i18n_text(None, "label_no", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Нет")
            template_label = get_i18n_text(None, "label_template", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Шаблон")
            owner_id_label = get_i18n_text(None, "label_owner_id", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Владелец ID")
            location_id_label = get_i18n_text(None, "label_location_id", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Локация ID")
            leader_id_label = get_i18n_text(None, "label_leader_id", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Лидер ID")
            members_label = get_i18n_text(None, "label_members", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Участники")
            none_label = get_i18n_text(None, "label_none", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="нет")
            unknown_label = get_i18n_text(None, "label_unknown", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="Неизвестно")
            na_label = get_i18n_text(None, "label_na", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text="N/A")

            entity_obj_dict = entity_obj.to_dict() if hasattr(entity_obj, 'to_dict') and callable(getattr(entity_obj, 'to_dict')) else (entity_obj if isinstance(entity_obj, dict) else {})
            entity_display_name_inner = get_i18n_text(entity_obj_dict.get('name_i18n') if isinstance(entity_obj_dict.get('name_i18n'), dict) else None, 'name_i18n', lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text=entity_obj_dict.get('name', unknown_label))

            entity_type_display_placeholder_inner = get_i18n_text(None, f"entity_type_{entity_type_str.lower()}", lang, default_lang=DEFAULT_BOT_LANGUAGE, guild_id=guild_id_for_i18n, default_text=entity_type_str)

            details += f"{type_label}: {entity_type_display_placeholder_inner}\n"
            details += f"{name_label}: {entity_display_name_inner}\n"
            if entity_type_str in ['Character', 'NPC']:
                 health_val = entity_obj_dict.get('hp', na_label)
                 max_health_val = entity_obj_dict.get('max_health', na_label)
                 details += f"{health_label}: {health_val}/{max_health_val}\n"
                 is_alive_val = yes_label if entity_obj_dict.get('is_alive', False) else no_label
                 details += f"{alive_label}: {is_alive_val}\n"
            elif entity_type_str == 'Item':
                 details += f"{template_label}: {entity_obj_dict.get('template_id', na_label)}\n"
                 details += f"{owner_id_label}: {entity_obj_dict.get('owner_id', none_label)}\n"
                 details += f"{location_id_label}: {entity_obj_dict.get('location_id', none_label)}\n"
            elif entity_type_str == 'Party':
                 details += f"{leader_id_label}: {entity_obj_dict.get('leader_id', none_label)}\n"
                 members = entity_obj_dict.get('members', [])
                 members_count = len(members) if isinstance(members, list) else 0
                 members_list_str = ', '.join(str(m) for m in members) if members else none_label
                 details += f"{members_label} ({members_count}): {members_list_str}\n"
            return details

        description_text += _format_basic_entity_details_placeholder(entity, entity_type, player_lang, guild_id, {})
        print(f"WorldViewService: Entity details generated for {entity_type} ID {entity_id} in language {player_lang}.")
        return description_text
