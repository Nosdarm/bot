import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

# Models and Services to test/mock
from bot.game.managers.economy_manager import EconomyManager
from bot.services.db_service import DBService # For type hint
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.managers.relationship_manager import RelationshipManager

# --- Fixtures ---

@pytest.fixture
def mock_item_manager_for_eco():
    manager = AsyncMock(spec=ItemManager)
    manager.get_item_template_by_id = AsyncMock()
    manager.create_item = AsyncMock(return_value=str(uuid.uuid4())) # Returns new item ID
    manager.move_item = AsyncMock(return_value=True)
    manager.get_item_instance = AsyncMock() # For sell_item
    return manager

@pytest.fixture
def mock_character_manager_for_eco():
    manager = AsyncMock(spec=CharacterManager)
    manager.deduct_currency = AsyncMock(return_value=True) # Default success
    manager.add_currency = AsyncMock(return_value=True) # Default success
    manager.remove_item_from_inventory = AsyncMock(return_value=True) # Default success
    return manager

@pytest.fixture
def mock_npc_manager_for_eco(): # Though not directly used in buy/sell examples yet
    manager = AsyncMock(spec=NpcManager)
    return manager

@pytest.fixture
def mock_rule_engine_for_eco():
    engine = AsyncMock(spec=RuleEngine)
    engine.calculate_market_price = AsyncMock()
    return engine

@pytest.fixture
def economy_manager(
    mock_item_manager_for_eco: ItemManager,
    mock_character_manager_for_eco: CharacterManager,
    mock_npc_manager_for_eco: NpcManager,
    mock_rule_engine_for_eco: RuleEngine
) -> EconomyManager:
    # For these unit/integration tests of EconomyManager, DBService, LocationManager, etc.
    # can be simple mocks if their direct complex interactions are not tested here.
    return EconomyManager(
        db_service=AsyncMock(spec=DBService),
        settings={},
        item_manager=mock_item_manager_for_eco,
        location_manager=AsyncMock(spec=LocationManager),
        character_manager=mock_character_manager_for_eco,
        npc_manager=mock_npc_manager_for_eco,
        rule_engine=mock_rule_engine_for_eco,
        time_manager=AsyncMock(),
        game_log_manager=AsyncMock(spec=GameLogManager),
        relationship_manager=AsyncMock(spec=RelationshipManager)
    )

# --- Tests for EconomyManager ---

@pytest.mark.asyncio
async def test_calculate_price_calls_rule_engine(
    economy_manager: EconomyManager,
    mock_rule_engine_for_eco: AsyncMock
):
    guild_id = "eco_guild1"
    loc_id = "market_loc"
    item_tpl_id = "sword1"
    quantity = 2
    actor_id = "player1"
    actor_type = "Character"

    mock_rule_engine_for_eco.calculate_market_price.return_value = 100.0 # Price per unit

    price, feedback = await economy_manager.calculate_price(
        guild_id, loc_id, item_tpl_id, quantity, is_selling=False,
        actor_entity_id=actor_id, actor_entity_type=actor_type
    )

    assert price == 100.0 * quantity # Assuming calculate_market_price returns price for the total quantity
    # If calculate_market_price returns price per unit, then the manager should multiply by quantity.
    # The current RuleEngine.calculate_market_price seems to take quantity and calculate total.
    # So, if RE returns 100.0, it's for quantity 2.
    # Let's adjust the mock to simulate price per unit for a more common scenario.
    # No, the RE.calculate_market_price takes quantity, so it should return total.

    # Let's assume RE.calculate_market_price returns the total price for the given quantity.
    mock_rule_engine_for_eco.calculate_market_price.return_value = 200.0 # Price for 2 units
    price, feedback = await economy_manager.calculate_price(
        guild_id, loc_id, item_tpl_id, quantity, is_selling=False,
        actor_entity_id=actor_id, actor_entity_type=actor_type
    )
    assert price == 200.0

    mock_rule_engine_for_eco.calculate_market_price.assert_awaited_once_with(
        guild_id=guild_id, location_id=loc_id, item_template_id=item_tpl_id,
        quantity=float(quantity), is_selling_to_market=False,
        actor_entity_id=actor_id, actor_entity_type=actor_type,
        economy_manager=economy_manager # RuleEngine might need this for context
    )
    assert feedback is not None

@pytest.mark.asyncio
async def test_buy_item_success(
    economy_manager: EconomyManager,
    mock_rule_engine_for_eco: AsyncMock,
    mock_character_manager_for_eco: AsyncMock,
    mock_item_manager_for_eco: AsyncMock
):
    guild_id = "buy_guild1"
    buyer_id = "buyer_char1"
    buyer_type = "Character"
    loc_id = "shop_loc1"
    item_tpl_id = "potion_healing"
    count = 2

    # Setup market inventory
    economy_manager._market_inventories[guild_id] = {loc_id: {item_tpl_id: 5.0}} # 5 available

    mock_rule_engine_for_eco.calculate_market_price.return_value = 50.0 # Total cost for 2 potions

    new_item_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    mock_item_manager_for_eco.create_item.side_effect = new_item_ids

    created_ids = await economy_manager.buy_item(
        guild_id, buyer_id, buyer_type, loc_id, item_tpl_id, count
    )

    assert created_ids == new_item_ids
    mock_character_manager_for_eco.deduct_currency.assert_awaited_once_with(
        guild_id=guild_id, entity_id=buyer_id, amount=50.0
    )
    # Check market inventory was updated
    assert economy_manager.get_market_inventory(guild_id, loc_id)[item_tpl_id] == 3.0 # 5 - 2
    assert loc_id in economy_manager._dirty_market_inventories[guild_id]

    # Check item creation and movement
    assert mock_item_manager_for_eco.create_item.call_count == count
    mock_item_manager_for_eco.create_item.assert_any_call(guild_id=guild_id, item_data={'template_id': item_tpl_id})

    assert mock_item_manager_for_eco.move_item.call_count == count
    mock_item_manager_for_eco.move_item.assert_any_call(
        guild_id=guild_id, item_id=new_item_ids[0], new_owner_id=buyer_id,
        new_location_id=None, new_owner_type=buyer_type
    )

@pytest.mark.asyncio
async def test_buy_item_insufficient_stock(economy_manager: EconomyManager):
    guild_id = "buy_guild_no_stock"
    loc_id = "shop_low_stock"
    item_tpl_id = "rare_gem"
    economy_manager._market_inventories[guild_id] = {loc_id: {item_tpl_id: 1.0}} # Only 1 available

    created_ids = await economy_manager.buy_item(
        guild_id, "buyer2", "Character", loc_id, item_tpl_id, count=2 # Requesting 2
    )
    assert created_ids is None # Should fail

@pytest.mark.asyncio
async def test_buy_item_insufficient_funds(
    economy_manager: EconomyManager,
    mock_rule_engine_for_eco: AsyncMock,
    mock_character_manager_for_eco: AsyncMock
):
    guild_id = "buy_guild_no_funds"
    loc_id = "shop_expensive"
    item_tpl_id = "diamond_ring"
    economy_manager._market_inventories[guild_id] = {loc_id: {item_tpl_id: 1.0}}
    mock_rule_engine_for_eco.calculate_market_price.return_value = 1000.0
    mock_character_manager_for_eco.deduct_currency.return_value = False # Deduction fails

    created_ids = await economy_manager.buy_item(
        guild_id, "buyer3", "Character", loc_id, item_tpl_id, count=1
    )
    assert created_ids is None

# --- Tests for sell_item ---
@pytest.mark.asyncio
async def test_sell_item_success(
    economy_manager: EconomyManager,
    mock_rule_engine_for_eco: AsyncMock,
    mock_character_manager_for_eco: AsyncMock,
    mock_item_manager_for_eco: AsyncMock
):
    guild_id = "sell_guild1"
    seller_id = "seller_char1"
    seller_type = "Character"
    loc_id = "market_sell"
    item_instance_id = "item_to_sell_123"
    item_tpl_id_of_instance = "common_dagger"

    mock_item_instance = MagicMock()
    mock_item_instance.owner_id = seller_id
    mock_item_instance.owner_type = seller_type
    mock_item_instance.template_id = item_tpl_id_of_instance
    mock_item_instance.quantity = 1.0
    mock_item_manager_for_eco.get_item_instance.return_value = mock_item_instance

    mock_rule_engine_for_eco.calculate_market_price.return_value = 20.0 # Market buys for 20

    revenue = await economy_manager.sell_item(
        guild_id, seller_id, seller_type, loc_id, item_instance_id, count=1 # count=1 for single instance
    )

    assert revenue == 20.0
    mock_item_manager_for_eco.get_item_instance.assert_awaited_once_with(guild_id, item_instance_id)
    mock_character_manager_for_eco.remove_item_from_inventory.assert_awaited_once_with(
        guild_id=guild_id, entity_id=seller_id, item_id=item_instance_id
    )
    mock_character_manager_for_eco.add_currency.assert_awaited_once_with(
        guild_id=guild_id, entity_id=seller_id, amount=20.0
    )
    # Check market inventory was updated
    assert economy_manager.get_market_inventory(guild_id, loc_id)[item_tpl_id_of_instance] == 1.0
    assert loc_id in economy_manager._dirty_market_inventories[guild_id]

@pytest.mark.asyncio
async def test_sell_item_not_owned(
    economy_manager: EconomyManager,
    mock_item_manager_for_eco: AsyncMock
):
    guild_id = "sell_guild_not_owned"
    mock_item_manager_for_eco.get_item_instance.return_value = None # Item not found or not owned

    revenue = await economy_manager.sell_item(
        guild_id, "seller2", "Character", "market2", "item_other_owner", 1
    )
    assert revenue is None

# TODO: Add more tests for failure cases in buy/sell (e.g., manager methods returning False/None)

print("DEBUG: tests/game/managers/test_economy_manager.py created.")
