import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from typing import Dict

from bot.game.managers.npc_manager import NpcManager
from bot.database.models import NPC as SQLAlchemyNPC
from bot.database.models import Location as DBLocation # For mocking location object
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.fixture
def mock_npc_templates() -> Dict:
    return {
        "guard": {
            "name_i18n": {"en": "Guard"},
            "stats": {"hp": 100, "strength": 12},
            "archetype": "humanoid_fighter",
            "faction_id": "city_guard_template_faction", # Template faction
            # No inventory in guard template by default for these tests
        },
        "goblin": {
            "name_i18n": {"en": "Goblin"},
            "stats": {"hp": 30, "strength": 8},
            "archetype": "goblin_basic",
            "inventory": [{"item_template_id": "rusty_dagger", "quantity": 1}] # Template inventory
            # No faction in goblin template by default
        }
    }

@pytest.fixture
def npc_manager_fixture(mock_npc_templates: Dict):
    # Mock DBService as it's checked in spawn_npc_in_location
    mock_db_service = AsyncMock()
    manager = NpcManager(db_service=mock_db_service)
    manager._npc_archetypes = mock_npc_templates
    manager._location_manager = AsyncMock()
    return manager

@pytest.mark.asyncio
async def test_spawn_npc_with_factions_and_inventory(npc_manager_fixture: NpcManager):
    # Arrange
    guild_id = "test_guild"
    location_id = "loc_castle_courtyard"
    npc_template_id = "guard" # Guard template has a faction_id
    mock_session = AsyncMock(spec=AsyncSession)

    initial_faction_id = "city_watch_override" # Override template's faction_id
    initial_faction_details = [
        {"faction_id": "city_watch_override", "rank_i18n": {"en": "Sergeant"}},
        {"faction_id": "kings_guard", "rank_i18n": {"en": "Reservist"}}
    ]
    initial_inventory = [
        {"item_template_id": "long_sword", "quantity": 1},
        {"item_template_id": "healing_potion", "quantity": 2}
    ]

    initial_state = {
        "name_i18n": {"en": "Custom Guard"},
        "faction_id": initial_faction_id,
        "faction_details_list": initial_faction_details,
        "inventory": initial_inventory,
        "stats": {"hp": 120}
    }

    mock_location = DBLocation(id=location_id, guild_id=guild_id, npc_ids=[])
    mock_session.get = AsyncMock(return_value=mock_location)

    # Act
    created_npc = await npc_manager_fixture.spawn_npc_in_location(
        guild_id, location_id, npc_template_id,
        initial_state=initial_state, session=mock_session, is_temporary=False
    )

    # Assert
    assert created_npc is not None
    assert isinstance(created_npc, SQLAlchemyNPC)
    mock_session.add.assert_any_call(created_npc)

    assert created_npc.name_i18n["en"] == "Custom Guard"
    assert created_npc.faction_id == initial_faction_id # Overridden
    assert created_npc.faction == initial_faction_details
    assert created_npc.inventory == initial_inventory
    assert created_npc.stats["hp"] == 120
    assert created_npc.stats["strength"] == 12
    assert created_npc.is_temporary is False

    mock_session.add.assert_any_call(mock_location)
    assert created_npc.id in mock_location.npc_ids


@pytest.mark.asyncio
async def test_spawn_npc_no_initial_faction_or_inventory_uses_template_values(npc_manager_fixture: NpcManager):
    # Arrange
    guild_id = "test_guild"
    location_id = "loc_forest_edge"
    npc_template_id = "goblin" # Goblin template has inventory, no faction
    mock_session = AsyncMock(spec=AsyncSession)
    initial_state = {} # Empty initial_state

    mock_location = DBLocation(id=location_id, guild_id=guild_id, npc_ids=[])
    mock_session.get = AsyncMock(return_value=mock_location)

    # Act
    created_npc = await npc_manager_fixture.spawn_npc_in_location(
        guild_id, location_id, npc_template_id,
        initial_state=initial_state, session=mock_session
    )

    # Assert
    assert created_npc is not None
    template_data = npc_manager_fixture.get_npc_template(guild_id, npc_template_id)

    assert created_npc.faction_id == template_data.get("faction_id") # Should be None from goblin template
    assert created_npc.faction == template_data.get("faction_details_list") # Should be None
    assert created_npc.inventory == template_data.get("inventory") # Should be from goblin template
    assert created_npc.inventory == [{"item_template_id": "rusty_dagger", "quantity": 1}]

@pytest.mark.asyncio
async def test_spawn_npc_initial_state_overrides_template_inventory(npc_manager_fixture: NpcManager):
    # Arrange
    guild_id = "test_guild"
    location_id = "loc_cave_entrance"
    npc_template_id = "goblin"
    mock_session = AsyncMock(spec=AsyncSession)
    new_inventory = [{"item_template_id": "shiny_rock", "quantity": 3}]
    initial_state = {"inventory": new_inventory}

    mock_location = DBLocation(id=location_id, guild_id=guild_id, npc_ids=[])
    mock_session.get = AsyncMock(return_value=mock_location)

    # Act
    created_npc = await npc_manager_fixture.spawn_npc_in_location(
        guild_id, location_id, npc_template_id,
        initial_state=initial_state, session=mock_session
    )

    # Assert
    assert created_npc is not None
    assert created_npc.inventory == new_inventory


@pytest.mark.asyncio
async def test_spawn_npc_empty_list_initial_inventory_overrides_template(npc_manager_fixture: NpcManager):
    # Arrange
    guild_id = "test_guild"
    location_id = "loc_clearing"
    npc_template_id = "goblin"
    mock_session = AsyncMock(spec=AsyncSession)
    initial_state = {"inventory": []} # Explicitly empty inventory list

    mock_location = DBLocation(id=location_id, guild_id=guild_id, npc_ids=[])
    mock_session.get = AsyncMock(return_value=mock_location)

    # Act
    created_npc = await npc_manager_fixture.spawn_npc_in_location(
        guild_id, location_id, npc_template_id,
        initial_state=initial_state, session=mock_session
    )

    # Assert
    assert created_npc is not None
    assert created_npc.inventory == []


@pytest.mark.asyncio
async def test_spawn_npc_inventory_none_in_initial_state_overrides_template(npc_manager_fixture: NpcManager):
    # Arrange
    guild_id = "test_guild"
    location_id = "loc_swamp"
    npc_template_id = "goblin"
    mock_session = AsyncMock(spec=AsyncSession)
    initial_state = {"inventory": None} # Explicitly None inventory

    mock_location = DBLocation(id=location_id, guild_id=guild_id, npc_ids=[])
    mock_session.get = AsyncMock(return_value=mock_location)

    # Act
    created_npc = await npc_manager_fixture.spawn_npc_in_location(
        guild_id, location_id, npc_template_id,
        initial_state=initial_state, session=mock_session
    )

    # Assert
    assert created_npc is not None
    assert created_npc.inventory is None # Should be None (SQL NULL)

