# bot/game/managers/item_manager.py

import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

# Импорт модели Item (для аннотаций и работы с объектами)
from bot.game.models.item import Item

# Адаптер БД
from bot.database.sqlite_adapter import SqliteAdapter

if TYPE_CHECKING:
    # Чтобы не создавать циклических импортов, импортируем эти типы только для подсказок
    from bot.game.managers.location_manager import LocationManager
    from bot.game.rules.rule_engine import RuleEngine


class ItemManager:
    """
    Менеджер для создания, хранения и персистенции предметов.
    Не держит внутреннего состояния мира — только кеш и шаблоны.
    """
    def __init__(
        self,
        db_adapter: Optional[SqliteAdapter] = None,
        settings: Optional[Dict[str, Any]] = None,
        location_manager: Optional['LocationManager'] = None,
        rule_engine: Optional['RuleEngine'] = None,
    ):
        print("Initializing ItemManager...")
        self._db_adapter = db_adapter
        self._settings = settings
        self._location_manager = location_manager
        self._rule_engine = rule_engine

        # Кеш экземпляров предметов: {item_id: Item}
        self._items: Dict[str, Item] = {}

        # Статические шаблоны предметов: {template_id: data_dict}
        self._item_templates: Dict[str, Dict[str, Any]] = {}

        # Изменённые экземпляры, подлежащие записи
        self._dirty_items: Set[str] = set()

        # Удалённые экземпляры, подлежащие удалению из БД
        self._deleted_item_ids: Set[str] = set()

        # Загружаем статические шаблоны
        self._load_item_templates()
        print("ItemManager initialized.")

    def _load_item_templates(self) -> None:
        """(Пример) Загружает статические шаблоны из настроек или файлов."""
        print("ItemManager: Loading item templates...")
        try:
            if self._settings and 'item_templates' in self._settings:
                self._item_templates = self._settings['item_templates']
            # Иначе можно читать из JSON-файла:
            # else:
            #     with open(self._settings.get('item_templates_file', 'data/items.json')) as f:
            #         self._item_templates = json.load(f)

            print(f"ItemManager: Loaded {len(self._item_templates)} item templates.")
        except Exception as e:
            print(f"ItemManager: Error loading item templates: {e}")
            traceback.print_exc()

    def get_item_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Возвращает данные шаблона по его ID."""
        return self._item_templates.get(template_id)

    def get_item_name(self, item_id: str) -> Optional[str]:
        """
        Возвращает имя экземпляра предмета, глядя в его шаблон.
        """
        item = self._items.get(item_id)
        if not item:
            return None
        tpl = self.get_item_template(item.template_id)
        if tpl:
            return tpl.get('name', f"Unknown({item.template_id})")
        return f"Unknown({item.template_id})"

    def get_item(self, item_id: str) -> Optional[Item]:
        """Возвращает экземпляр предмета из кеша."""
        return self._items.get(item_id)

    async def create_item(self, item_data: Dict[str, Any], **kwargs) -> Optional[str]:
        """
        Создаёт новый экземпляр предмета на основе item_data['template_id'],
        кладёт его в кеш и помечает для сохранения.
        """
        print(f"ItemManager: Creating item from template '{item_data.get('template_id')}'...")
        if not self._db_adapter:
            print("ItemManager: No DB adapter.")
            return None

        tpl_id = item_data.get('template_id')
        if not tpl_id:
            print("ItemManager: Missing 'template_id'.")
            return None

        try:
            new_id = str(uuid.uuid4())
            data = {
                'id': new_id,
                'template_id': tpl_id,
                'owner_id': item_data.get('owner_id'),
                'location_id': item_data.get('location_id'),
                'is_temporary': item_data.get('is_temporary', False),
                'state_variables': item_data.get('state_variables', {}),
            }
            item = Item.from_dict(data)
            self._items[new_id] = item
            self._dirty_items.add(new_id)
            print(f"ItemManager: Item '{new_id}' created and marked dirty.")
            return new_id
        except Exception as e:
            print(f"ItemManager: Error creating item: {e}")
            traceback.print_exc()
            return None

    async def move_item(
        self,
        item_id: str,
        new_owner_id: Optional[str] = None,
        new_location_id: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        Меняет owner_id и/или location_id в кеше и помечает экземпляр dirty.
        """
        print(f"ItemManager: Moving item {item_id} → owner {new_owner_id}, loc {new_location_id}")
        item = self._items.get(item_id)
        if not item:
            print(f"ItemManager: Item {item_id} not found.")
            return False

        # Пример валидации локации (если нужно):
        # loc_mgr = kwargs.get('location_manager', self._location_manager)
        # if new_location_id and loc_mgr and not loc_mgr.get_location(new_location_id):
        #     print(f"ItemManager: Location {new_location_id} not found.")
        #     return False

        item.owner_id = new_owner_id
        item.location_id = new_location_id
        self._dirty_items.add(item_id)
        print(f"ItemManager: Item {item_id} marked dirty after move.")
        return True

    async def save_all_items(self) -> None:
        """
        Сохраняет все _dirty_items и удаляет те, что в _deleted_item_ids.
        Вызывается PersistenceManager.
        """
        if not self._db_adapter or (not self._dirty_items and not self._deleted_item_ids):
            return

        print(f"ItemManager: Saving {len(self._dirty_items)} items, deleting {len(self._deleted_item_ids)}...")
        try:
            # Удаляем:
            if self._deleted_item_ids:
                ph = ','.join('?' * len(self._deleted_item_ids))
                await self._db_adapter.execute(
                    f"DELETE FROM items WHERE id IN ({ph})",
                    tuple(self._deleted_item_ids)
                )
                self._deleted_item_ids.clear()

            # Сохраняем:
            for iid in list(self._dirty_items):
                itm = self._items.get(iid)
                if not itm:
                    self._dirty_items.discard(iid)
                    continue

                sql = """
                    INSERT OR REPLACE INTO items
                      (id, template_id, owner_id, location_id, is_temporary, state_variables)
                    VALUES (?, ?, ?, ?, ?, ?)
                """
                params = (
                    itm.id,
                    itm.template_id,
                    itm.owner_id,
                    itm.location_id,
                    int(itm.is_temporary),
                    json.dumps(itm.state_variables or {}),
                )
                await self._db_adapter.execute(sql, params)

            await self._db_adapter.commit()
            print(f"ItemManager: Saved {len(self._dirty_items)} items.")
            self._dirty_items.clear()
        except Exception as e:
            print(f"ItemManager: Error saving items: {e}")
            traceback.print_exc()
            if self._db_adapter:
                await self._db_adapter.rollback()

    async def load_all_items(self) -> None:
        """
        Загружает все строки из таблицы items → кеш _items.
        """
        print("ItemManager: Loading items from DB...")
        self._items.clear()
        self._dirty_items.clear()
        self._deleted_item_ids.clear()

        if not self._db_adapter:
            print("ItemManager: No DB adapter—it will work with empty cache.")
            return

        try:
            rows = await self._db_adapter.fetchall(
                "SELECT id, template_id, owner_id, location_id, is_temporary, state_variables FROM items"
            )
            for row in rows:
                data = dict(row)
                data['is_temporary'] = bool(data.get('is_temporary'))
                data['state_variables'] = json.loads(data.get('state_variables') or "{}")
                item = Item.from_dict(data)
                self._items[item.id] = item

            print(f"ItemManager: Loaded {len(self._items)} items.")
        except Exception as e:
            print(f"ItemManager: Error loading items: {e}")
            traceback.print_exc()

    def rebuild_runtime_caches(self) -> None:
        """
        Если у вас есть дополнительные кеши (по локации, по владельцу) — перестраивает их.
        """
        print("ItemManager: Rebuilding runtime caches...")
        # например:
        # self._items_by_location = {}
        # for itm in self._items.values():
        #     if itm.location_id:
        #         self._items_by_location.setdefault(itm.location_id, set()).add(itm.id)
        print("ItemManager: Runtime caches rebuilt.")
