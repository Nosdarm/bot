import time
import json
from typing import Dict, List, Any, Optional, Tuple, TypedDict

# Assuming DBService is defined and provides an async interface like fetchall
# from bot.services.db_service import DBService

class GameEntity(TypedDict):
    id: str
    name: str
    type: str
    lang: str
    parent_location_id: Optional[str] # For location_feature, location_tag
    intent_context: Optional[str] # Added for action verbs

# For the __main__ block, we'll create a MockDBService
class MockDBService:
    MOCK_DATA: Dict[str, List[Dict[str, Any]]] = {
        "locations": [
            {"id": "loc_001", "guild_id": "guild1", "name_i18n": json.dumps({"en": "Forest of Whispers", "ru": "Лес Шепотов"}), "features_i18n": json.dumps({"en": ["Old Tree", "Hidden Path"], "ru": ["Старое Дерево", "Тайная Тропа"]}), "tags_i18n": json.dumps({"en": ["forest", "dark"], "ru": ["лес", "темный"]})},
            {"id": "loc_002", "guild_id": "guild1", "name_i18n": json.dumps({"en": "Old Mill", "ru": "Старая Мельница"}), "features_i18n": json.dumps({"en": ["Grinding Stone"], "ru": ["Жернов"]}), "tags_i18n": json.dumps({"en": ["building"], "ru": ["строение"]})},
            {"id": "loc_003", "guild_id": "guild2", "name_i18n": json.dumps({"en": "Town Square", "ru": "Городская Площадь"}), "features_i18n": None, "tags_i18n": json.dumps({"en": ["town", "center"], "ru": ["город", "центр"]})},
        ],
        "location_templates": [
            {"id": "loc_tpl_001", "guild_id": "guild1", "name": "Generic Dungeon"}, # Non-i18n name
            {"id": "loc_tpl_002", "guild_id": None, "name": "Global Cave System"}, # Global
        ],
        "generated_locations": [
            {"id": "gen_loc_001", "name_i18n": json.dumps({"en": "Crystal Caves", "ru": "Кристальные Пещеры"}), "tags_i18n": json.dumps({"en": ["cave", "magic"], "ru": ["пещера", "магия"]})},
        ],
        "npcs": [
            {"id": "npc_001", "guild_id": "guild1", "name_i18n": json.dumps({"en": "Guard Captain", "ru": "Капитан Стражи"})},
            {"id": "npc_002", "guild_id": "guild2", "name_i18n": json.dumps({"en": "Mysterious Stranger", "ru": "Загадочный Незнакомец"})},
        ],
        "generated_npcs": [
            {"id": "gen_npc_001", "name_i18n": json.dumps({"en": "Traveling Merchant", "ru": "Странствующий Торговец"})},
        ],
        "items": [ # Now guild-specific
            {"id": "item_001", "guild_id": "guild1", "name_i18n": json.dumps({"en": "Health Potion", "ru": "Зелье Здоровья"})},
            {"id": "item_002", "guild_id": "guild1", "name_i18n": json.dumps({"en": "Steel Sword", "ru": "Стальной Меч"})},
            {"id": "item_003", "guild_id": "guild2", "name_i18n": json.dumps({"en": "Mana Potion", "ru": "Зелье Маны"})},
        ],
        "item_templates": [
            {"id": "item_tpl_001", "guild_id": "guild1", "name_i18n": json.dumps({"en": "Basic Herb", "ru": "Обычная Трава"})},
            {"id": "item_tpl_002", "guild_id": None, "name_i18n": json.dumps({"en": "Iron Ingot", "ru": "Железный Слиток"})}, # Global
        ],
        "item_properties": [
            {"id": "prop_001", "name_i18n": json.dumps({"en": "Flaming", "ru": "Пылающий"})},
            {"id": "prop_002", "name_i18n": json.dumps({"en": "Poisonous", "ru": "Ядовитый"})},
        ],
        "abilities": [
            {"id": "abil_001", "name_i18n": json.dumps({"en": "Fireball", "ru": "Огненный Шар"})},
        ],
        "skills": [
            {"id": "skill_001", "name_i18n": json.dumps({"en": "Lockpicking", "ru": "Взлом Замков"})},
        ],
        "statuses": [ # Assuming 'statuses' table holds definitions for NLU, not instances
            {"id": "status_001", "guild_id": "guild1", "name_i18n": json.dumps({"en": "Poisoned", "ru": "Отравлен"})},
            {"id": "status_002", "guild_id": "guild2", "name_i18n": json.dumps({"en": "Blessed", "ru": "Благословлен"})},
        ],
        "events": [
            {"id": "event_001", "guild_id": "guild1", "name_i18n": json.dumps({"en": "Goblin Ambush", "ru": "Засада Гоблинов"})},
        ]
    }

    async def fetchall(self, query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        print(f"MockDBService: Query: {query}, Params: {params}")
        table_name_search = query.split("FROM ")[1].split(" ")[0] if "FROM " in query else None

        data_to_filter = self.MOCK_DATA.get(table_name_search, [])

        if not params or not data_to_filter:
            return [row for row in data_to_filter if params or not row.get("guild_id")] # Return all if no params, or only global if params exist but table is global

        guild_id_param = params[0] if params else None

        # Simulate WHERE clause filtering
        # This mock filtering is simplified and might not cover all SQL nuances
        results = []
        for row in data_to_filter:
            guild_match = False
            if "guild_id = ?" in query and "guild_id IS NULL" in query: # (guild_id = ? OR guild_id IS NULL)
                if row.get("guild_id") == guild_id_param or row.get("guild_id") is None:
                    guild_match = True
            elif "guild_id = ?" in query:
                if row.get("guild_id") == guild_id_param:
                    guild_match = True
            elif "guild_id" not in row or row.get("guild_id") is None : # Global entity if table has no guild_id or it's null and query doesn't filter
                if not any(p for p in params if isinstance(p, str) and "guild" in p): # Crude check if query filters by guild
                     guild_match = True

            if guild_match:
                results.append(row)
        return results


ENTITY_CONFIG: Dict[str, Dict[str, Any]] = {
    "location": {"table": "locations", "name_field": "name_i18n", "type_name": "location", "guild_column": "guild_id", "tags_field": "tags_i18n", "tag_type_name": "location_tag", "features_field": "features_i18n", "feature_type_name": "location_feature"},
    "location_template": {"table": "location_templates", "name_field": "name", "type_name": "location_template", "guild_column": "guild_id", "nullable_guild": True},
    "generated_location": {"table": "generated_locations", "name_field": "name_i18n", "type_name": "generated_location", "guild_column": None, "tags_field": "tags_i18n", "tag_type_name": "location_tag"},
    "npc": {"table": "npcs", "name_field": "name_i18n", "type_name": "npc", "guild_column": "guild_id"},
    "generated_npc": {"table": "generated_npcs", "name_field": "name_i18n", "type_name": "generated_npc", "guild_column": None},
    "item": {"table": "items", "name_field": "name_i18n", "type_name": "item", "guild_column": "guild_id"},
    "item_template": {"table": "item_templates", "name_field": "name_i18n", "type_name": "item_template", "guild_column": "guild_id", "nullable_guild": True},
    "item_property": {"table": "item_properties", "name_field": "name_i18n", "type_name": "item_property", "guild_column": None},
    "ability": {"table": "abilities", "name_field": "name_i18n", "type_name": "ability", "guild_column": None},
    "skill": {"table": "skills", "name_field": "name_i18n", "type_name": "skill", "guild_column": None},
    "status": {"table": "statuses", "name_field": "name_i18n", "type_name": "status", "guild_column": "guild_id"},
    "event": {"table": "events", "name_field": "name_i18n", "type_name": "event", "guild_column": "guild_id"},
    "generated_faction": {"table": "generated_factions", "name_field": "name_i18n", "type_name": "faction", "guild_column": "guild_id"},
}

class NLUDataService:
    CACHE_TTL_SECONDS = 300

    def __init__(self, db_service: Any):
        if db_service is None:
            raise ValueError("NLUDataService requires a valid db_service instance.")
        self.db_service = db_service
        self._cache: Dict[Tuple[str, str, bool], Dict[str, Any]] = {} # Key: (guild_id, language, fetch_global_too)
        print("NLUDataService initialized with DBService.")

    def _get_i18n_name(self, raw_value: Optional[Any], language: str, is_i18n_field: bool = True, default_lang: str = "en") -> Optional[str]:
        """Safely extracts the name, handling i18n if specified."""
        if raw_value is None:
            return None

        if not is_i18n_field:
            return str(raw_value) if isinstance(raw_value, (str, int, float)) else None

        try:
            names = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
            if not isinstance(names, dict): return None

            name = names.get(language)
            if name is None:
                name = names.get(default_lang)
            return name
        except (json.JSONDecodeError, TypeError):
            return None

    async def get_game_entities(self, guild_id: str, language: str, fetch_global_too: bool = False) -> Dict[str, List[GameEntity]]:
        cache_key = (guild_id, language, fetch_global_too)
        current_time = time.time()

        if cache_key in self._cache:
            cached_item = self._cache[cache_key]
            if current_time - cached_item['timestamp'] < self.CACHE_TTL_SECONDS:
                print(f"NLUDataService: Cache hit for {cache_key}.")
                return cached_item['data']
            else:
                print(f"NLUDataService: Cache expired for {cache_key}.")
                del self._cache[cache_key]

        print(f"NLUDataService: Cache miss for {cache_key}. Fetching from DB.")

        all_entity_types = [cfg["type_name"] for cfg in ENTITY_CONFIG.values()]
        all_entity_types.append("location_feature") # Handled specially
        all_entity_types.append("location_tag")     # Handled specially
        all_entities: Dict[str, List[GameEntity]] = {entity_type: [] for entity_type in set(all_entity_types)}


        for config_key, config in ENTITY_CONFIG.items():
            table_name = config["table"]
            name_field = config["name_field"]
            type_name = config["type_name"]
            guild_column = config.get("guild_column")
            nullable_guild = config.get("nullable_guild", False)
            tags_field = config.get("tags_field")
            tag_type_name = config.get("tag_type_name")
            features_field = config.get("features_field") # For locations
            feature_type_name = config.get("feature_type_name") # For locations

            is_i18n_name = name_field.endswith("_i18n")
            
            select_fields = ["id", name_field]
            if tags_field: select_fields.append(tags_field)
            if features_field: select_fields.append(features_field)

            query = f"SELECT {', '.join(select_fields)} FROM {table_name}"
            params: List[Any] = []

            where_clauses = []
            if guild_column:
                if nullable_guild and fetch_global_too:
                    where_clauses.append(f"({guild_column} = ? OR {guild_column} IS NULL)")
                    params.append(guild_id)
                else:
                    where_clauses.append(f"{guild_column} = ?")
                    params.append(guild_id)

            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)

            query += ";"

            try:
                rows = await self.db_service.fetchall(query, tuple(params))
                for row in rows:
                    entity_name = self._get_i18n_name(row[name_field], language, is_i18n_field=is_i18n_name)
                    if entity_name:
                        all_entities[type_name].append(GameEntity(
                            id=str(row['id']), name=entity_name, type=type_name, lang=language, parent_location_id=None
                        ))

                    # Handle tags
                    if tags_field and tag_type_name and row.get(tags_field):
                        tags_data = self._get_i18n_name(row[tags_field], language, is_i18n_field=True) # Tags are assumed i18n list
                        if isinstance(tags_data, list): # Expecting list of strings after _get_i18n_name resolves language
                            for tag_name in tags_data:
                                if tag_name:
                                    all_entities[tag_type_name].append(GameEntity(
                                        id=f"{row['id']}_tag_{tag_name.replace(' ', '_').lower()}",
                                        name=tag_name, type=tag_type_name, lang=language,
                                        parent_location_id=str(row['id'])
                                    ))
                        elif tags_data: # If it's a single string (e.g. "tag1, tag2") - less ideal schema but handle defensively
                             for tag_name_part in tags_data.split(','):
                                tag_name_clean = tag_name_part.strip()
                                if tag_name_clean:
                                     all_entities[tag_type_name].append(GameEntity(
                                        id=f"{row['id']}_tag_{tag_name_clean.replace(' ', '_').lower()}",
                                        name=tag_name_clean, type=tag_type_name, lang=language,
                                        parent_location_id=str(row['id'])
                                    ))


                    # Handle features (specific to locations for now)
                    if features_field and feature_type_name and row.get(features_field):
                        features_data = self._get_i18n_name(row[features_field], language, is_i18n_field=True)
                        if isinstance(features_data, list):
                            for feature_name in features_data:
                                if feature_name:
                                    all_entities[feature_type_name].append(GameEntity(
                                        id=f"{row['id']}_feat_{feature_name.replace(' ', '_').lower()}",
                                        name=feature_name, type=feature_type_name, lang=language,
                                        parent_location_id=str(row['id'])
                                    ))
            except Exception as e:
                print(f"NLUDataService: Database error for table {table_name} (guild {guild_id}, lang {language}): {e}")

        # Fetch action verbs from RuleConfig
        try:
            from bot.database.models import RulesConfig # Import RulesConfig model
            action_verbs_rule_key = f"nlu.action_verbs.{language}"
            action_verbs_config_row = await self.db_service.get_entities_by_conditions(
                table_name='rules_config', # Direct table name
                conditions={'guild_id': guild_id, 'key': action_verbs_rule_key},
                single_entity=True
            )
            action_verbs_config = None
            if action_verbs_config_row and 'value' in action_verbs_config_row:
                action_verbs_config = action_verbs_config_row['value']

            if isinstance(action_verbs_config, dict):
                if "action_verb" not in all_entities:
                    all_entities["action_verb"] = []
                for intent, verbs in action_verbs_config.items():
                    if isinstance(verbs, list):
                        for verb_phrase in verbs:
                            all_entities["action_verb"].append(GameEntity(
                                id=f"verb_{intent}_{verb_phrase.replace(' ', '_').lower()}",
                                name=verb_phrase,
                                type="action_verb",
                                lang=language,
                                parent_location_id=None, # Not applicable for verbs
                                intent_context=intent # Store intent here
                            ))
            else:
                print(f"NLUDataService: No action verb configuration found for guild {guild_id}, lang {language} (key: {action_verbs_rule_key}) or data is not a dict.")
        except ImportError:
            print(f"NLUDataService: Could not import RulesConfig model, skipping action verb loading.")
        except Exception as e:
            print(f"NLUDataService: Error fetching or processing action verbs for guild {guild_id}, lang {language}: {e}")


        self._cache[cache_key] = {'timestamp': current_time, 'data': all_entities}
        if not any(all_entities.values()):
             print(f"NLUDataService: No game entities found or fetched from DB for {cache_key}.")
        return all_entities


if __name__ == '__main__':
    import asyncio

    async def test_service():
        mock_db_service = MockDBService()
        nlu_service = NLUDataService(db_service=mock_db_service)

        test_guild_id1 = "guild1"
        test_guild_id2 = "guild2"
        test_lang_en = "en"
        test_lang_ru = "ru"

        print(f"\n--- Test Run 1: English entities for {test_guild_id1} (no global) ---")
        entities_g1_en_local = await nlu_service.get_game_entities(test_guild_id1, test_lang_en, fetch_global_too=False)
        print(json.dumps(entities_g1_en_local, indent=2, ensure_ascii=False))

        assert len(entities_g1_en_local.get("location", [])) == 2 # loc_001, loc_002
        assert len(entities_g1_en_local.get("location_tag", [])) == 3 # forest, dark, building
        assert entities_g1_en_local["location_tag"][0]["name"] == "forest"
        assert entities_g1_en_local["location_tag"][0]["parent_location_id"] == "loc_001"
        assert entities_g1_en_local["location_feature"][0]["name"] == "Old Tree"
        assert len(entities_g1_en_local.get("item_template", [])) == 1 # Basic Herb
        assert entities_g1_en_local["item_template"][0]["name"] == "Basic Herb"
        assert len(entities_g1_en_local.get("location_template", [])) == 1 # Generic Dungeon

        print(f"\n--- Test Run 2: English entities for {test_guild_id1} (with global) ---")
        entities_g1_en_global = await nlu_service.get_game_entities(test_guild_id1, test_lang_en, fetch_global_too=True)
        print(json.dumps(entities_g1_en_global, indent=2, ensure_ascii=False))
        assert len(entities_g1_en_global.get("item_template", [])) == 2 # Basic Herb, Iron Ingot
        assert len(entities_g1_en_global.get("location_template", [])) == 2 # Generic Dungeon, Global Cave System
        assert len(entities_g1_en_global.get("generated_location", [])) == 1 # Crystal Caves (always global)
        assert len(entities_g1_en_global.get("item_property", [])) == 2 # Flaming, Poisonous (always global)

        print(f"\n--- Test Run 3: Russian entities for {test_guild_id2} (with global) ---")
        entities_g2_ru_global = await nlu_service.get_game_entities(test_guild_id2, test_lang_ru, fetch_global_too=True)
        print(json.dumps(entities_g2_ru_global, indent=2, ensure_ascii=False))
        assert len(entities_g2_ru_global.get("location", [])) == 1 # Городская Площадь
        assert entities_g2_ru_global["location"][0]["name"] == "Городская Площадь"
        assert len(entities_g2_ru_global.get("npc", [])) == 1 # Загадочный Незнакомец
        assert len(entities_g2_ru_global.get("item", [])) == 1 # Зелье Маны
        assert len(entities_g2_ru_global.get("item_template", [])) == 1 # Iron Ingot (global only, guild2 has no specific)
        assert entities_g2_ru_global["item_template"][0]["name"] == "Железный Слиток"
        assert len(entities_g2_ru_global.get("status",[])) == 1 # Благословлен (guild2)

        print(f"\n--- Test Run 4: Cache check for {test_guild_id1} (en, with global) ---")
        entities_g1_en_global_cache = await nlu_service.get_game_entities(test_guild_id1, test_lang_en, fetch_global_too=True)
        assert entities_g1_en_global_cache == entities_g1_en_global # Should be from cache

        print("\nNLUDataService tests completed based on provided spec.")

    asyncio.run(test_service())
