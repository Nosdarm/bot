from __future__ import annotations
import json  # Может понадобиться для работы с данными правил из JSON
import traceback  # Для вывода трассировки ошибок
import asyncio  # Если методы RuleEngine будут асинхронными

from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    # Модели, которые вы упоминаете в аннотациях
    from bot.game.models.character import Character
    from bot.game.models.npc import NPC
    from bot.game.models.party import Party
    from bot.game.models.combat import Combat
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.npc_manager import NpcManager


from bot.game.managers.location_manager import LocationManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.party_manager import PartyManager





class RuleEngine:
    """
    Система правил для вычисления результатов действий, проверок условий,
    расчётов (урон, длительность, проверки) и AI-логики.
    Работает с данными мира, полученными из менеджеров через контекст.
    """
    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        print("Initializing RuleEngine...")
        self._settings = settings or {}
        self._rules_data: Dict[str, Any] = {}
        print("RuleEngine initialized.")

    async def load_rules_data(self) -> None:
        """
        Загружает правила из настроек или других источников.
        """
        print("RuleEngine: Loading rules data...")
        self._rules_data = self._settings.get('rules_data', {})
        print(f"RuleEngine: Loaded {len(self._rules_data)} rules entries.")

    async def calculate_action_duration(
        self,
        action_type: str,
        action_context: Dict[str, Any],
        character: Optional[Character] = None,
        npc: Optional[NPC] = None,
        party: Optional[Party] = None,
        **context,
    ) -> float:
        """
        Рассчитывает длительность действия в игровых минутах.
        Менеджеры доступны через context.
        """
        # Пример: перемещение
        if action_type == 'move':
            lm: Optional[LocationManager] = context.get('location_manager')
            curr = getattr(character or npc, 'location_id', None)
            target = action_context.get('target_location_id')
            if curr and target and lm:
                base = float(self._rules_data.get('base_move_duration_per_location', 5.0))
                return base
            return 0.0

        # Пример: атака
        if action_type == 'combat_attack':
            return float(self._rules_data.get('base_attack_duration', 1.0))

        # Другие действия
        if action_type == 'rest':
            return float(action_context.get('duration', 10.0))
        if action_type == 'search':
            return float(self._rules_data.get('base_search_duration', 5.0))
        if action_type == 'craft':
            return float(self._rules_data.get('base_craft_duration', 30.0))
        if action_type == 'use_item':
            return float(self._rules_data.get('base_use_item_duration', 1.0))
        if action_type == 'ai_dialogue':
            return float(self._rules_data.get('base_dialogue_step_duration', 0.1))
        if action_type == 'idle':
            return float(self._rules_data.get('default_idle_duration', 60.0))

        print(f"RuleEngine: Warning: Unknown action type '{action_type}'. Returning 0.0.")
        return 0.0

    async def check_conditions(
        self,
        conditions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> bool:
        """
        Проверяет список условий; возвращает True, если все выполнены.
        """
        if not conditions:
            return True
        # Менеджеры из context
        cm: Optional[CharacterManager] = context.get('character_manager')
        nm: Optional[NpcManager] = context.get('npc_manager')
        lm: Optional[LocationManager] = context.get('location_manager')
        im: Optional[ItemManager] = context.get('item_manager')
        pm: Optional[PartyManager] = context.get('party_manager')
        sm: Optional[StatusManager] = context.get('status_manager')
        combat: Optional[CombatManager] = context.get('combat_manager')

        for cond in conditions:
            ctype = cond.get('type')
            data = cond.get('data', {})
            met = False
            if ctype == 'has_item' and im:
                ent = context.get('character') or context.get('npc') or context.get('party')
                eid = getattr(ent, 'id', None)
                if eid:
                    met = await im.check_entity_has_item(
                        eid,
                        type(ent).__name__,
                        item_template_id=data.get('item_template_id'),
                        item_id=data.get('item_id'),
                        quantity=data.get('quantity', 1),
                        context=context
                    )
            elif ctype == 'in_location' and lm:
                eid = data.get('entity_id') or getattr(context.get('character') or context.get('npc'), 'id', None)
                loc = data.get('location_id')
                if eid and loc:
                    ent = None
                    et = data.get('entity_type')
                    if et == 'Character' and cm: ent = cm.get_character(eid)
                    if et == 'NPC' and nm: ent = nm.get_npc(eid)
                    if ent and getattr(ent, 'location_id', None) == loc:
                        met = True
            elif ctype == 'has_status' and sm:
                eid = data.get('entity_id') or getattr(context.get('character') or context.get('npc'), 'id', None)
                st = data.get('status_type')
                et = data.get('entity_type') or ('Character' if context.get('character') else 'NPC')
                if eid and st:
                    statuses = sm.get_status_effects_on_entity_by_type(eid, et, st, context=context)
                    met = bool(statuses)
            elif ctype == 'stat_check':
                eid = data.get('entity_id') or getattr(context.get('character') or context.get('npc'), 'id', None)
                et = data.get('entity_type') or ('Character' if context.get('character') else 'NPC')
                stat = data.get('stat')
                thresh = data.get('threshold')
                op = data.get('operator', '>=')
                ent_obj = None
                if et == 'Character' and cm: ent_obj = cm.get_character(eid)
                if et == 'NPC' and nm: ent_obj = nm.get_npc(eid)
                if ent_obj:
                    met = await self.perform_stat_check(ent_obj, stat, thresh, op, context=context)
            elif ctype == 'is_in_combat' and combat:
                eid = data.get('entity_id') or getattr(context.get('character') or context.get('npc'), 'id', None)
                if eid and combat.get_combat_by_participant_id(eid):
                    met = True
            elif ctype == 'is_leader_of_party' and pm:
                eid = data.get('entity_id') or getattr(context.get('character') or context.get('npc'), 'id', None)
                party = pm.get_party_by_member_id(eid) if eid else None
                if party and getattr(party, 'leader_id', None) == eid:
                    met = True
            else:
                print(f"RuleEngine: Warning: Unknown condition '{ctype}'.")
                return False

            if not met:
                return False

        return True

    async def choose_combat_action_for_npc(
        self,
        npc: NPC,
        combat: Combat,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Простая AI-логика боевого действия NPC.
        """
        cm: Optional[CharacterManager] = context.get('character_manager')
        nm: Optional[NpcManager] = context.get('npc_manager')
        cman: Optional[CombatManager] = context.get('combat_manager')

        # Получаем участников
        if cman:
            living = cman.get_living_participants(combat.id)
            for p in living:
                if p.entity_id != npc.id:
                    return {'type': 'combat_attack', 'target_id': p.entity_id, 'target_type': p.entity_type, 'attack_type': 'basic_attack'}
        return {'type': 'idle', 'total_duration': None}

    async def can_rest(
        self,
        npc: NPC,
        context: Dict[str, Any]
    ) -> bool:
        """Проверяет возможность отдыха NPC."""
        cman: Optional[CombatManager] = context.get('combat_manager')
        lm: Optional[LocationManager] = context.get('location_manager')
        if cman and cman.get_combat_by_participant_id(npc.id):
            return False
        # Дополнительные проверки по локации и статусам
        return True

    def handle_stage(self, stage: Any, **context) -> None:
        # Локальный импорт для разрыва циклов
        from bot.game.event_processors.event_stage_processor import EventStageProcessor
        proc = EventStageProcessor()
        proc.process(stage, **context)

    async def choose_peaceful_action_for_npc(
        self,
        npc: NPC,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        AI-логика спокойного поведения NPC.
        """
        lm: Optional[LocationManager] = context.get('location_manager')
        cm: Optional[CharacterManager] = context.get('character_manager')
        nm: Optional[NpcManager] = context.get('npc_manager')
        dm = context.get('dialogue_manager')

        # Попытка диалога
        curr_loc = getattr(npc, 'location_id', None)
        if dm and cm and lm and curr_loc:
            chars = cm.get_characters_in_location(curr_loc)
            for ch in chars:
                if ch.id != npc.id and dm.can_start_dialogue:
                    return {'type': 'ai_dialogue', 'target_id': ch.id, 'target_type': 'Character'}
        # Блуждание
        if curr_loc and lm:
            exits = lm.get_connected_locations(curr_loc)
            if exits:
                import random
                _, dest = random.choice(list(exits.items()))
                return {'type': 'move', 'target_location_id': dest}
        return {'type': 'idle', 'total_duration': None}
