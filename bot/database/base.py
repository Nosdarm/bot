from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta
from sqlalchemy.types import TypeDecorator, JSON
from sqlalchemy.dialects.postgresql import JSONB

class JsonVariant(TypeDecorator):
    """Represents a JSON type that uses JSONB for PostgreSQL
    and JSON for other dialects."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(JSON())

Base: DeclarativeMeta = declarative_base()
