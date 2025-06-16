# tests/database/test_crud_utils.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import crud_utils
from bot.database.models import Base
import sqlalchemy as sa # Import sqlalchemy for Column definition

# Dummy Model for testing
class MockGuildSpecificModel(Base):
    __tablename__ = "mock_guild_specific"
    # Define actual SQLAlchemy columns for primary key and guild_id
    id = sa.Column(sa.String, primary_key=True)
    guild_id = sa.Column(sa.String)
    name = sa.Column(sa.String) # Mock other fields as needed for testing setattr
    value = sa.Column(sa.Integer)

    # Keep __init__ for easy instantiation in tests
    def __init__(self, **kwargs):
        super().__init__() # Call Base's __init__ if it has one, or just handle kwargs
        for k, v in kwargs.items():
            # Only set attributes that are actual columns or expected by tests
            if hasattr(self.__class__, k) or k in ['id', 'guild_id', 'name', 'value']:
                 setattr(self, k, v)
            else:
                # Optionally log or raise error for unexpected kwargs in tests, or ignore
                pass

    # __sa_instance_state__ is automatically managed by SQLAlchemy for real models.
    # For a manually constructed mock like this, if specific tests trigger deep SA interaction
    # that requires it, it might need further mocking. Usually not for basic CRUD.
    # If tests fail due to its absence, it can be added:
    # __sa_instance_state__ = MagicMock()


@pytest.fixture
def mock_db_session():
    session = AsyncMock(spec=AsyncSession)
    session.in_transaction.return_value = False # Default for transactional decorator tests

    # Configure the session.begin() to return an async context manager
    mock_transaction_context = AsyncMock()
    session.begin.return_value = mock_transaction_context

    # Make commit and rollback awaitable
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()

    return session

@pytest.mark.asyncio
async def test_create_entity_success(mock_db_session):
    data = {"name": "Test Name", "value": 100}
    guild_id = "test_guild_123"

    # Data for the new entity. guild_id will be added by create_entity
    # or verified if already present.
    data_to_create = data.copy()

    # No need to mock the constructor if we are passing the class directly.
    # crud_utils.create_entity will call MockGuildSpecificModel(**data_with_guild_id)
    created_entity = await crud_utils.create_entity(
        mock_db_session, MockGuildSpecificModel, data_to_create, guild_id
    )

    # Assert that data_to_create (which was passed to the constructor by create_entity)
    # now contains the guild_id.
    # The create_entity function modifies the 'data' dict in-place if guild_id is not present.
    # If guild_id was already in data, it should match.
    # The actual instance 'created_entity' will have .guild_id set by its __init__

    # Check that add and flush were called with an instance that has the correct guild_id
    # The instance passed to add() is created inside create_entity.
    # We need to check the attributes of the object passed to session.add().
    args_on_add, _ = mock_db_session.add.call_args
    added_instance = args_on_add[0] # This is the instance passed to session.add()

    assert isinstance(added_instance, MockGuildSpecificModel)
    assert added_instance.name == data["name"]
    assert added_instance.value == data["value"]
    assert added_instance.guild_id == guild_id

    # Verify that session.add was called with this instance
    mock_db_session.add.assert_called_once_with(added_instance)
    mock_db_session.flush.assert_awaited_once()
    # The created_entity is the added_instance, so its attributes are already checked.
    # No separate mock_instance exists in this version of the test.
    assert created_entity == added_instance
    assert created_entity.guild_id == guild_id # type: ignore

@pytest.mark.asyncio
async def test_create_entity_with_conflicting_guild_id(mock_db_session):
    data = {"name": "Test Name", "value": 100, "guild_id": "other_guild"}
    guild_id = "test_guild_123"

    with pytest.raises(ValueError, match="guild_id in data conflicts with the guild_id parameter."):
        await crud_utils.create_entity(
            mock_db_session, MockGuildSpecificModel, data.copy(), guild_id
        )
    mock_db_session.add.assert_not_called()

@pytest.mark.asyncio
async def test_create_entity_integrity_error(mock_db_session):
    data = {"name": "Test Name Duplicate", "value": 200}
    guild_id = "test_guild_456"

    mock_db_session.flush.side_effect = IntegrityError("Mock IntegrityError", params=None, orig=None)

    with pytest.raises(IntegrityError):
        await crud_utils.create_entity(
            mock_db_session, MockGuildSpecificModel, data.copy(), guild_id
        )
    # Rollback is expected to be handled by a transactional decorator/context, not by create_entity itself.

@pytest.mark.asyncio
async def test_get_entity_by_id_found(mock_db_session):
    entity_id = "entity_pk_1"
    guild_id = "guild_abc"

    mock_instance = MockGuildSpecificModel(id=entity_id, guild_id=guild_id, name="Found Entity")

    # Mock SQLAlchemy query execution flow for: result = await db_session.execute(stmt); entity = result.scalars().first()
    mock_execute_result = AsyncMock()      # Returned by awaited session.execute()
    mock_scalars_result = MagicMock()      # Returned by result.scalars() (sync method)
    mock_scalars_result.first.return_value = mock_instance # .first() is a sync method on ScalarResult

    mock_execute_result.scalars = MagicMock(return_value=mock_scalars_result)
    mock_db_session.execute.return_value = mock_execute_result

    found_entity = await crud_utils.get_entity_by_id(
        mock_db_session, MockGuildSpecificModel, entity_id, guild_id
    )

    mock_db_session.execute.assert_awaited_once()
    assert found_entity == mock_instance
    assert found_entity.id == entity_id # type: ignore
    assert found_entity.guild_id == guild_id # type: ignore

@pytest.mark.asyncio
async def test_get_entity_by_id_not_found(mock_db_session):
    entity_id = "entity_pk_2"
    guild_id = "guild_xyz"

    mock_execute_result = AsyncMock()
    mock_scalars_result = MagicMock()
    mock_scalars_result.first.return_value = None # Simulate not found
    mock_execute_result.scalars = MagicMock(return_value=mock_scalars_result)
    mock_db_session.execute.return_value = mock_execute_result

    found_entity = await crud_utils.get_entity_by_id(
        mock_db_session, MockGuildSpecificModel, entity_id, guild_id
    )
    assert found_entity is None

@pytest.mark.asyncio
async def test_get_entity_by_id_found_but_wrong_guild(mock_db_session):
    entity_id = "entity_pk_3"
    # correct_guild_id = "guild_correct" # Not needed for mock setup, only for logic
    wrong_guild_id = "guild_wrong"

    mock_execute_result = AsyncMock()
    mock_scalars_result = MagicMock()
    mock_scalars_result.first.return_value = None # Simulate not found due to guild_id mismatch in query
    mock_execute_result.scalars = MagicMock(return_value=mock_scalars_result)
    mock_db_session.execute.return_value = mock_execute_result

    found_entity = await crud_utils.get_entity_by_id(
        mock_db_session, MockGuildSpecificModel, entity_id, wrong_guild_id
    )
    assert found_entity is None
    # We would also assert that the generated SQL (if we could inspect it) includes
    # AND guild_id == wrong_guild_id

@pytest.mark.asyncio
async def test_get_entities_clauses_application(mock_db_session):
    guild_id = "guild_clauses"

    # Mock the select object chain
    mock_select_stmt = MagicMock()
    mock_where_stmt = MagicMock()
    mock_orderby_stmt = MagicMock()
    mock_limit_stmt = MagicMock()
    mock_offset_stmt = MagicMock()

    # Simulate the chaining: select(...).where(...).where(...).order_by(...).limit(...).offset(...)
    # This requires crud_utils to use a real select object initially, which is then chained.
    # For simplicity, let's assume crud_utils gets a select object and chains it.
    # We will mock the select() call from sqlalchemy.future used within get_entities

    mock_initial_select = MagicMock()
    mock_initial_select.where.return_value = mock_where_stmt # First where (guild_id)
    mock_where_stmt.where.return_value = mock_where_stmt # Subsequent wheres for conditions
    mock_where_stmt.order_by.return_value = mock_orderby_stmt
    mock_orderby_stmt.limit.return_value = mock_limit_stmt
    mock_limit_stmt.offset.return_value = mock_offset_stmt # Final stmt before execute

    mock_execute_result = AsyncMock()
    mock_scalars_result = MagicMock() # Corrected from mock_scalars_obj
    mock_scalars_result.all.return_value = []
    mock_execute_result.scalars = MagicMock(return_value=mock_scalars_result)
    mock_db_session.execute.return_value = mock_execute_result

    # Dummy conditions and order_by
    from sqlalchemy import column
    conditions = [MockGuildSpecificModel.name == "Test"]
    order_by_clauses = [MockGuildSpecificModel.name.desc()]

    with patch("bot.database.crud_utils.select", return_value=mock_initial_select) as mock_select_func:
        await crud_utils.get_entities(
            mock_db_session,
            MockGuildSpecificModel,
            guild_id,
            conditions=conditions,
            order_by=order_by_clauses,
            limit=5,
            offset=10
        )

    mock_select_func.assert_called_once_with(MockGuildSpecificModel)
    # Check guild_id where clause
    assert mock_initial_select.where.call_args is not None # Check it was called
    # Check additional conditions (assuming one condition for simplicity of this mock structure)
    mock_where_stmt.where.assert_called_once_with(conditions[0])
    # Check order_by
    mock_where_stmt.order_by.assert_called_once_with(order_by_clauses[0])
    # Check limit
    mock_orderby_stmt.limit.assert_called_once_with(5)
    # Check offset
    mock_limit_stmt.offset.assert_called_once_with(10)
    # Check execute was called with the final statement object
    mock_db_session.execute.assert_awaited_once_with(mock_offset_stmt)


@pytest.mark.asyncio
async def test_get_entities_success(mock_db_session): # Keep this simpler test for basic success
    guild_id = "guild_qwerty"
    mock_entity1 = MockGuildSpecificModel(id="1", guild_id=guild_id, name="Entity 1")
    mock_entity2 = MockGuildSpecificModel(id="2", guild_id=guild_id, name="Entity 2")

    mock_execute_result = AsyncMock()
    mock_scalars_result = MagicMock() # Corrected from mock_scalars_obj
    mock_scalars_result.all.return_value = [mock_entity1, mock_entity2]
    mock_execute_result.scalars = MagicMock(return_value=mock_scalars_result)
    mock_db_session.execute.return_value = mock_execute_result

    entities = await crud_utils.get_entities(mock_db_session, MockGuildSpecificModel, guild_id)

    assert len(entities) == 2
    assert entities[0].name == "Entity 1" # type: ignore
    assert mock_db_session.execute.call_args is not None


@pytest.mark.asyncio
async def test_update_entity_success(mock_db_session):
    guild_id = "guild_update_success"
    entity_id = "upd_entity_1"
    original_instance = MockGuildSpecificModel(id=entity_id, guild_id=guild_id, name="Original Name")
    update_data = {"name": "Updated Name", "value": 500}

    updated_entity = await crud_utils.update_entity(
        mock_db_session, original_instance, update_data, guild_id
    )

    assert updated_entity.name == "Updated Name" # type: ignore
    assert updated_entity.value == 500 # type: ignore
    mock_db_session.add.assert_called_once_with(original_instance)
    mock_db_session.flush.assert_awaited_once()

@pytest.mark.asyncio
async def test_update_entity_guild_id_mismatch(mock_db_session):
    original_instance = MockGuildSpecificModel(id="mismatch_1", guild_id="actual_guild_id", name="Mismatch Test")
    update_data = {"name": "New Name"}

    with pytest.raises(ValueError, match="Guild ID mismatch"):
        await crud_utils.update_entity(
            mock_db_session, original_instance, update_data, "attempted_wrong_guild_id"
        )
    mock_db_session.add.assert_not_called()

@pytest.mark.asyncio
async def test_delete_entity_success(mock_db_session):
    guild_id = "guild_delete_success"
    entity_id = "del_entity_1"
    instance_to_delete = MockGuildSpecificModel(id=entity_id, guild_id=guild_id, name="To Be Deleted")

    result = await crud_utils.delete_entity(mock_db_session, instance_to_delete, guild_id)

    assert result is True
    mock_db_session.delete.assert_awaited_once_with(instance_to_delete)
    mock_db_session.flush.assert_awaited_once()

@pytest.mark.asyncio
async def test_delete_entity_guild_id_mismatch(mock_db_session):
    instance_to_delete = MockGuildSpecificModel(id="del_mismatch_1", guild_id="actual_guild_id_del", name="Delete Mismatch Test")

    with pytest.raises(ValueError, match="Guild ID mismatch"):
        await crud_utils.delete_entity(mock_db_session, instance_to_delete, "attempted_wrong_guild_id_del")
    mock_db_session.delete.assert_not_called()


@pytest.mark.asyncio
async def test_get_entity_by_attributes_found(mock_db_session):
    guild_id = "guild_attr_find"
    attributes = {"name": "Attribute Search"}
    mock_instance = MockGuildSpecificModel(id="attr_1", guild_id=guild_id, name="Attribute Search", value=123)

    mock_execute_result = AsyncMock()
    mock_scalars_result = MagicMock() # Corrected from mock_scalars_obj
    mock_scalars_result.first.return_value = mock_instance
    mock_execute_result.scalars = MagicMock(return_value=mock_scalars_result)
    mock_db_session.execute.return_value = mock_execute_result

    found_entity = await crud_utils.get_entity_by_attributes(
        mock_db_session, MockGuildSpecificModel, attributes, guild_id
    )
    assert found_entity == mock_instance
    assert found_entity.name == "Attribute Search" # type: ignore

# --- Transactional Decorator Tests ---

# Dummy function to be decorated
async def sample_db_operation(db_session: AsyncSession, data: str, should_fail: bool = False):
    # Simulate DB work
    if should_fail:
        raise ValueError("Simulated DB operation failure")
    return f"Processed: {data}"

@pytest.mark.asyncio
async def test_transactional_decorator_commit(mock_db_session):
    decorated_op = crud_utils.transactional_session(session_param_name='db_session')(sample_db_operation)

    result = await decorated_op(db_session=mock_db_session, data="test_commit")

    assert result == "Processed: test_commit"
    mock_db_session.begin.assert_called_once() # Check that a transaction was started
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.rollback.assert_not_awaited()

@pytest.mark.asyncio
async def test_transactional_decorator_rollback(mock_db_session):
    decorated_op = crud_utils.transactional_session(session_param_name='db_session')(sample_db_operation)

    with pytest.raises(ValueError, match="Simulated DB operation failure"):
        await decorated_op(db_session=mock_db_session, data="test_rollback", should_fail=True)

    mock_db_session.begin.assert_called_once()
    mock_db_session.commit.assert_not_awaited()
    mock_db_session.rollback.assert_awaited_once()

@pytest.mark.asyncio
async def test_transactional_decorator_already_in_transaction(mock_db_session):
    mock_db_session.in_transaction.return_value = True # Simulate already being in a transaction

    decorated_op = crud_utils.transactional_session(session_param_name='db_session')(sample_db_operation)

    result = await decorated_op(db_session=mock_db_session, data="test_nested")

    assert result == "Processed: test_nested"
    mock_db_session.begin.assert_not_called() # Should not start a new transaction
    mock_db_session.commit.assert_not_awaited() # Should not commit (outer transaction handles it)
    mock_db_session.rollback.assert_not_awaited()

# TODO: Add more tests for edge cases, different parameter passing to decorator, etc.
# TODO: Test how the decorator finds the session if not passed as kwarg (this part is fragile).
# For example, test with `decorated_op(mock_db_session, "test_data_pos_arg")`
# This would require the decorator's arg parsing to be more robust or tests to adapt.
# The current decorator arg parsing logic is very basic.
# A more robust approach would be to require session to be a keyword argument.

# Example of how a class method would be decorated (conceptual for testing)
class DummyService:
    def __init__(self, db_session_factory): # Or just pass a session for simple tests
        self.db_session_factory = db_session_factory # Not used by current decorator version

    @crud_utils.transactional_session(session_param_name='actual_session_name')
    async def my_service_method(self, actual_session_name: AsyncSession, some_data: str):
        return await sample_db_operation(db_session=actual_session_name, data=some_data)

@pytest.mark.asyncio
async def test_transactional_decorator_with_custom_session_param_name(mock_db_session):
    service_instance = DummyService(None) # Factory not used by this decorator version

    result = await service_instance.my_service_method(actual_session_name=mock_db_session, some_data="custom_param_test")

    assert result == "Processed: custom_param_test"
    mock_db_session.begin.assert_called_once()
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.rollback.assert_not_awaited()

# Test for session passed as positional argument (if decorator supports it well)
# This requires the decorator's argument introspection to be more sophisticated
# or the test to align with its current simple positional logic.
# The decorator currently checks args[1] if args[0] is not a session (assuming 'self').
# This is brittle. A better decorator might use inspect.signature.

@pytest.mark.asyncio
async def test_transactional_decorator_session_as_positional_arg(mock_db_session):
    # This test is for a standalone function where db_session is the first positional arg

    # Re-wrap with default 'db_session' name for this test structure
    @crud_utils.transactional_session()
    async def standalone_op_pos(db_session: AsyncSession, data: str):
        return await sample_db_operation(db_session=db_session, data=data)

    result = await standalone_op_pos(mock_db_session, "pos_arg_test")
    assert result == "Processed: pos_arg_test"
    mock_db_session.begin.assert_called_once()
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.rollback.assert_not_awaited()

@pytest.mark.asyncio
async def test_transactional_decorator_session_as_positional_arg_in_method(mock_db_session):
    # Test a method where 'self' is first, then the session
    class ServiceWithPositionalSession:
        @crud_utils.transactional_session() # Assumes session param is 'db_session'
        async def method_with_pos_session(self, db_session: AsyncSession, data: str):
            return await sample_db_operation(db_session=db_session, data=data)

    service = ServiceWithPositionalSession()
    result = await service.method_with_pos_session(mock_db_session, "method_pos_arg_test")
    assert result == "Processed: method_pos_arg_test"
    mock_db_session.begin.assert_called_once()
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.rollback.assert_not_awaited()

# Test for model without guild_id for guild-aware functions
class MockNonGuildModel(Base):
    __tablename__ = "mock_non_guild"
    id = sa.Column(sa.String, primary_key=True) # Correct PK definition
    name = sa.Column(sa.String)

    def __init__(self, **kwargs): # Add __init__ for consistency
        super().__init__()
        for k, v in kwargs.items():
            if hasattr(self.__class__, k) or k in ['id', 'name']:
                 setattr(self, k, v)


@pytest.mark.asyncio
async def test_get_entity_by_id_non_guild_aware_model(mock_db_session):
    entity = await crud_utils.get_entity_by_id(mock_db_session, MockNonGuildModel, "1", "any_guild")
    assert entity is None # Expect it to fail gracefully or as designed

@pytest.mark.asyncio
async def test_get_entities_non_guild_aware_model(mock_db_session):
    entities = await crud_utils.get_entities(mock_db_session, MockNonGuildModel, "any_guild")
    assert entities == []

@pytest.mark.asyncio
async def test_update_entity_non_guild_aware_model(mock_db_session):
    instance = MockNonGuildModel(id="1", name="test")
    result = await crud_utils.update_entity(mock_db_session, instance, {"name": "new"}, "any_guild")
    assert result is None # Or raises error, depending on desired strictness (currently returns None)

@pytest.mark.asyncio
async def test_delete_entity_non_guild_aware_model(mock_db_session):
    instance = MockNonGuildModel(id="1", name="test")
    result = await crud_utils.delete_entity(mock_db_session, instance, "any_guild")
    assert result is False # Or raises error
