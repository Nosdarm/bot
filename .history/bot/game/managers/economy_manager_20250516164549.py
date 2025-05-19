# bot/game/managers/economy_manager.py

import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable

from bot.database.sqlite_adapter import SqliteAdapter
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.time_manager import TimeManager


class EconomyManager:
    """
    Менеджер для управления игровой экономикой:
    рынки, запасы, расчёт цен и торговые операции.
    """
    def __init__(
        self,
        db_adapter: Optional[SqliteAdapter] = None,
        settings: Optional[Dict[str, Any]] = None,

        item_manager: Optional['ItemManager'] = None,
        location_manager: Optional['LocationManager'] = None,
        character_manager: Optional['CharacterManager'] = None,
        npc_manager: Optional['NpcManager'] = None,
        rule_engine: Optional['RuleEngine'] = None,
        time_manager: Optional['TimeManager'] = None,
    ):
        print("Initializing EconomyManager...")
        self._db_adapter = db_adapter
        self._settings = settings

        self._item_manager = item_manager
        self._location_manager = location_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._rule_engine = rule_engine
        self._time_manager = time_manager

        # {location_id: {item_template_id: count}}
        self._market_inventories: Dict[str, Dict[str, int]] = {}
        self._dirty_market_inventories: Set[str] = set()
        self._deleted_market_inventory_ids: Set[str] = set()

        print("EconomyManager initialized.\n")

    def get_market_inventory(self, location_id: str) -> Optional[Dict[str, int]]:
        inv = self._market_inventories.get(location_id)
        return dict(inv) if inv is not None else None

    async def add_items_to_market(
        self,
        location_id: str,
        items_data: Dict[str, int],
        **kwargs
    ) -> bool:
        print(f"EconomyManager: Adding {items_data} to market {location_id}")
        if not items_data:
            return False

        if self._location_manager and hasattr(self._location_manager, 'get_location_static'):
            if self._location_manager.get_location_static(location_id) is None:
                print(f"EconomyManager: Location {location_id} not found.")
                return False

        inv = self._market_inventories.get(location_id, {})
        if not isinstance(inv, dict):
            inv = {}

        for tpl, cnt in items_data.items():
            if cnt > 0:
                inv[tpl] = inv.get(tpl, 0) + cnt
                print(f"EconomyManager: +{cnt} of {tpl}")

        self._market_inventories[location_id] = inv
        self._dirty_market_inventories.add(location_id)
        print(f"EconomyManager: Market {location_id} marked dirty.")
        return True

    async def remove_items_from_market(
        self,
        location_id: str,
        items_data: Dict[str, int],
        **kwargs
    ) -> bool:
        print(f"EconomyManager: Removing {items_data} from market {location_id}")
        inv = self._market_inventories.get(location_id)
        if not inv or not isinstance(inv, dict):
            print(f"EconomyManager: No inventory for {location_id}")
            return False

        for tpl, cnt in items_data.items():
            if inv.get(tpl, 0) < cnt:
                print(f"EconomyManager: Not enough {tpl} ({inv.get(tpl, 0)}/{cnt})")
                return False

        for tpl, cnt in items_data.items():
            if cnt > 0:
                inv[tpl] -= cnt
                if inv[tpl] <= 0:
                    inv.pop(tpl)
                print(f"EconomyManager: -{cnt} of {tpl}")

        self._market_inventories[location_id] = inv
        self._dirty_market_inventories.add(location_id)
        print(f"EconomyManager: Market {location_id} marked dirty.")
        return True

    async def buy_item(
        self,
        buyer_entity_id: str,
        buyer_entity_type: str,
        location_id: str,
        item_template_id: str,
        count: int = 1,
        **kwargs
    ) -> Optional[List[str]]:
        # Простейший заглушечный вариант
        print(f"EconomyManager: Buy {count}×{item_template_id} @ {location_id} by {buyer_entity_type} {buyer_entity_id}")
        total_cost = 10 * count  # placeholder
        self._dirty_market_inventories.add(location_id)
        purchased = [str(uuid.uuid4()) for _ in range(count)]
        print(f"EconomyManager: Placeholder bought IDs {purchased}, cost {total_cost}")
        return purchased

    async def sell_item(
        self,
        seller_entity_id: str,
        seller_entity_type: str,
        location_id: str,
        item_id: str,
        count: int = 1,
        **kwargs
    ) -> Optional[float]:
        print(f"EconomyManager: Sell {count}×{item_id} @ {location_id} by {seller_entity_type} {seller_entity_id}")
        total_rev = 5 * count  # placeholder
        self._dirty_market_inventories.add(location_id)
        print(f"EconomyManager: Placeholder sale revenue {total_rev}")
        return float(total_rev)

    async def process_tick(self, game_time_delta: float, **kwargs) -> None:
        if self._db_adapter is None:
            return
        # Здесь можно добавить ресток/изменение цен по таймеру
        pass

    async def save_all_state(self) -> None:
        """
        Сохраняет состояние рынков в БД:
        и удаляет те, что помечены на удаление.
        """
        if (
            self._db_adapter is None
            or (
                not self._dirty_market_inventories
                and not getattr(self, '_deleted_market_inventory_ids', None)
            )
        ):
            return

        dirty = len(self._dirty_market_inventories)
        deleted = len(getattr(self, '_deleted_market_inventory_ids', []))
        print(
            f"EconomyManager: Saving {dirty} dirty markets "
            f"and processing {deleted} deleted markets..."
        )

        try:
            # Удаляем помеченные
            deleted_set = getattr(self, '_deleted_market_inventory_ids', set()) or set()
            if deleted_set:
                ids_list = list(deleted_set)
                placeholders = ','.join('?' for _ in ids_list)
                sql_del = (
                    f"DELETE FROM market_inventories "
                    f"WHERE location_id IN ({placeholders})"
                )
                await self._db_adapter.execute(sql_del, tuple(ids_list))
                print(f"EconomyManager: Deleted {len(ids_list)} rows.")
                deleted_set.clear()

            # Сохраняем изменённые
            for loc_id in list(self._dirty_market_inventories):
                inv = self._market_inventories.get(loc_id, {})
                inv_json = json.dumps(inv)
                sql_ins = """
                    INSERT OR REPLACE INTO market_inventories
                    (location_id, inventory)
                    VALUES (?, ?)
                """
                await self._db_adapter.execute(sql_ins, (loc_id, inv_json))

            await self._db_adapter.commit()
            print(f"EconomyManager: Successfully saved {dirty} markets.")
            self._dirty_market_inventories.clear()

        except Exception as e:
            print(f"EconomyManager: ❌ Error saving state: {e}")
            traceback.print_exc()
            if self._db_adapter:
                await self._db_adapter.rollback()
            raise

    async def load_all_state(self) -> None:
        """
        Загружает все рынки из БД в кеш.
        """
        print("EconomyManager: Loading all economy state from DB...")
        self._market_inventories = {}
        self._dirty_market_inventories = set()
        self._deleted_market_inventory_ids = set()

        if self._db_adapter is None:
            print("EconomyManager: No DB adapter, skipping load.")
            return

        try:
            rows = await self._db_adapter.fetchall(
                "SELECT location_id, inventory FROM market_inventories"
            )
            for row in rows:
                loc = row['location_id']
                inv_str = row['inventory'] or '{}'
                inv = json.loads(inv_str)
                if isinstance(inv, dict):
                    self._market_inventories[loc] = {k: int(v) for k, v in inv.items()}
                else:
                    print(f"EconomyManager: Bad format for {loc}, skipping.")

            print(f"EconomyManager: Loaded {len(self._market_inventories)} markets.")
        except Exception as e:
            print(f"EconomyManager: ❌ Error loading state: {e}")
            traceback.print_exc()
            raise

    def rebuild_runtime_caches(self) -> None:
        """
        Перестраивает вспомогательные кеши (если будут).
        """
        print("EconomyManager: Rebuilding runtime caches...")
        # сейчас ничего лишнего делать не нужно
        print("EconomyManager: Runtime caches rebuilt.")
