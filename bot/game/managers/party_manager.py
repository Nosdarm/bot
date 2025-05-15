# bot/game/managers/party_manager.py

import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

from bot.database.sqlite_adapter import SqliteAdapter
from bot.game.models.party import Party  # модель Party, безопасно

if TYPE_CHECKING:
    # Эти импорты нужны только для аннотаций типов и не выполняются в рантайме
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.combat_manager import CombatManager

class PartyManager:
    """
    Менеджер для управления группами (parties).
    Хранит состояние всех партий, CRUD, проверку busy-статуса, и т.п.
    """
    def __init__(self,
                 db_adapter: Optional[SqliteAdapter] = None,
                 settings: Optional[Dict[str, Any]] = None,
                 npc_manager: Optional['NpcManager'] = None,
                 character_manager: Optional['CharacterManager'] = None,
                 combat_manager: Optional['CombatManager'] = None,
                 # event_manager: Optional['EventManager'] = None,  # если нужен
                ):
        self._db_adapter = db_adapter
        self._settings = settings

        # Инжектированные зависимости
        self._npc_manager = npc_manager
        self._character_manager = character_manager
        self._combat_manager = combat_manager
        # self._event_manager = event_manager

        # Кеш партий: {party_id: Party}
        self._parties: Dict[str, Party] = {}

        # Для оптимизации персистенции
        self._dirty_parties: Set[str] = set()
        self._deleted_parties: Set[str] = set()

    def get_party(self, party_id: str) -> Optional[Party]:
        return self._parties.get(party_id)

    def get_all_parties(self) -> List[Party]:
        return list(self._parties.values())

    async def create_party(self, leader_id: str, member_ids: List[str], **kwargs) -> Optional[str]:
        """
        Создает новую партию с лидером и списком участников.
        """
        if self._db_adapter is None:
            print("PartyManager: No DB adapter.")
            return None

        try:
            new_id = str(uuid.uuid4())
            party_data = {
                'id': new_id,
                'leader_id': leader_id,
                'member_ids': member_ids.copy(),
                'state_variables': {},
            }
            party = Party.from_dict(party_data)

            self._parties[new_id] = party
            self._dirty_parties.add(new_id)

            # Помечаем участников «занятыми» — если нужно, можно логику вписать сюда
            return new_id
        except Exception as e:
            print(f"PartyManager: Error creating party: {e}")
            traceback.print_exc()
            return None

    async def remove_party(self, party_id: str, **kwargs) -> Optional[str]:
        """
        Удаляет партию и помечает для удаления в БД.
        """
        party = self.get_party(party_id)
        if not party:
            print(f"PartyManager: Party {party_id} not found.")
            return None

        # Очистка: можно выгнать участников, обновить их статус и т.п.
        # Например, освободить NPC:
        if self._npc_manager:
            for npc_id in party.member_ids:
                # Например, сбросить party_id в NPC:
                npc = self._npc_manager.get_npc(npc_id)
                if npc:
                    npc.party_id = None
                    self._npc_manager._dirty_npcs.add(npc_id)

        # Удаляем из кеша
        self._parties.pop(party_id)
        self._deleted_parties.add(party_id)
        self._dirty_parties.discard(party_id)

        return party_id

    def is_party_busy(self, party_id: str) -> bool:
        """
        Считает, занята ли партия групповым действием.
        """
        party = self.get_party(party_id)
        if not party:
            return False
        return party.current_action is not None

    # Методы персистенции (вызываются PersistenceManager):

    async def save_all_parties(self) -> None:
        if self._db_adapter is None or (not self._dirty_parties and not self._deleted_parties):
            return

        try:
            # Удалённые
            if self._deleted_parties:
                dels = list(self._deleted_parties)
                sql_del = f"DELETE FROM parties WHERE id IN ({','.join('?'*len(dels))})"
                await self._db_adapter.execute(sql_del, tuple(dels))
                self._deleted_parties.clear()

            # Изменённые
            for pid in list(self._dirty_parties):
                party = self._parties.get(pid)
                if not party:
                    self._dirty_parties.discard(pid)
                    continue

                members_json = json.dumps(party.member_ids)
                state_json   = json.dumps(party.state_variables or {})

                sql = """
                    INSERT OR REPLACE INTO parties
                    (id, leader_id, member_ids, state_variables, current_action)
                    VALUES (?, ?, ?, ?, ?)
                """
                params = (
                    party.id,
                    party.leader_id,
                    members_json,
                    state_json,
                    json.dumps(party.current_action) if party.current_action else None
                )
                await self._db_adapter.execute(sql, params)

            await self._db_adapter.commit()
            self._dirty_parties.clear()

        except Exception as e:
            print(f"PartyManager: Error saving parties: {e}")
            traceback.print_exc()
            if self._db_adapter:
                await self._db_adapter.rollback()

    async def load_all_parties(self) -> None:
        if self._db_adapter is None:
            print("PartyManager: No DB adapter, skipping load.")
            return

        self._parties.clear()
        self._dirty_parties.clear()
        self._deleted_parties.clear()

        try:
            rows = await self._db_adapter.fetchall(
                "SELECT id, leader_id, member_ids, state_variables, current_action FROM parties"
            )
            for row in rows:
                try:
                    rd = dict(row)
                    rd['member_ids']       = json.loads(rd.get('member_ids') or '[]')
                    rd['state_variables']  = json.loads(rd.get('state_variables') or '{}')
                    rd['current_action']   = json.loads(rd.get('current_action') or 'null')
                    party = Party.from_dict(rd)
                    self._parties[party.id] = party
                except Exception as e:
                    print(f"PartyManager: Error loading row {row.get('id')}: {e}")
                    traceback.print_exc()
            print(f"PartyManager: Loaded {len(self._parties)} parties.")
        except Exception as e:
            print(f"PartyManager: Error loading parties: {e}")
            traceback.print_exc()

    def rebuild_runtime_caches(self) -> None:
        """
        Если есть дополнительные кеши (например, по лидеру или члену),
        их можно перестроить здесь.
        """
        pass
