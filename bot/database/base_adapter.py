from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, Any, Union, Dict

class BaseDbAdapter(ABC):
    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    async def execute(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> str:
        pass

    @abstractmethod
    async def execute_insert(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> Optional[Any]:
        pass

    @abstractmethod
    async def execute_many(self, sql: str, data: List[Union[Tuple, List]]) -> None:
        pass

    @abstractmethod
    async def fetchall(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def fetchone(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def commit(self) -> None:
        pass

    @abstractmethod
    async def rollback(self) -> None:
        pass

    @abstractmethod
    async def initialize_database(self) -> None:
        pass

    @abstractmethod
    async def begin_transaction(self) -> None:
        pass

    # Methods for pending_conflicts
    @abstractmethod
    async def save_pending_conflict(self, conflict_id: str, guild_id: str, conflict_data: str) -> None:
        pass

    @abstractmethod
    async def get_pending_conflict(self, conflict_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def delete_pending_conflict(self, conflict_id: str) -> None:
        pass

    @abstractmethod
    async def get_pending_conflicts_by_guild(self, guild_id: str) -> List[Dict[str, Any]]:
        pass

    # Methods for pending_moderation_requests
    @abstractmethod
    async def save_pending_moderation_request(self, request_id: str, guild_id: str, user_id: str, content_type: str, data_json: str, status: str = 'pending') -> None:
        pass

    @abstractmethod
    async def get_pending_moderation_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def update_pending_moderation_request(
        self, request_id: str, status: str, moderator_id: Optional[str],
        data_json: Optional[str] = None, moderator_notes: Optional[str] = None
    ) -> bool:
        pass

    @abstractmethod
    async def delete_pending_moderation_request(self, request_id: str) -> bool:
        pass

    @abstractmethod
    async def get_pending_requests_by_guild(self, guild_id: str, status: str = 'pending') -> List[Dict[str, Any]]:
        pass

    # Method for generated_locations
    @abstractmethod
    async def add_generated_location(self, location_id: str, guild_id: str, user_id: str) -> None:
        pass

    # Method for upsert_location
    @abstractmethod
    async def upsert_location(self, location_data: Dict[str, Any]) -> bool:
        pass

    @property
    @abstractmethod
    def supports_returning_id_on_insert(self) -> bool:
        """Indicates if the adapter supports 'RETURNING id' (or equivalent) on insert."""
        pass

    @property
    @abstractmethod
    def json_column_type_cast(self) -> Optional[str]:
        """The string to use for casting to a JSON type (e.g., '::jsonb') or None if not needed."""
        pass
