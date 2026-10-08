import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.init_db import DEFAULT_ROLES  # noqa: F401
from app.db.session import build_engine
from app.models import (
    Client, CustomField, CustomValue, Deal, EntityType, FieldType, Role, Status, StatusEntity, User,
)


@pytest.fixture()
def db():
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _client_with_vin(db: Session) -> tuple[Client, CustomField]:
    field = CustomField(entity_type=EntityType.CLIENT, code="vin", label="VIN", field_type=FieldType.TEXT)
    client = Client(name="Иван")
    db.add_all([field, client])
    db.flush()
    value = CustomValue(field_id=field.id, client_id=client.id)
    value.field = field
    value.set_value("XTA210930Y2765432")
    db.add(value)
    db.commit()
    return client, field


def test_custom_value_roundtrip(db):
    client, _ = _client_with_vin(db)
    db.expire_all()
    assert db.get(Client, client.id).custom == {"vin": "XTA210930Y2765432"}


def test_deleting_client_cascades_values(db):
    client, _ = _client_with_vin(db)
    db.delete(client)
    db.commit()
    assert db.scalar(select(CustomValue)) is None


def test_value_needs_exactly_one_owner(db):
    field = CustomField(entity_type=EntityType.CLIENT, code="x", label="X", field_type=FieldType.TEXT)
    db.add(field)
    db.flush()
    db.add(CustomValue(field_id=field.id, value_text="orphan"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_unique_value_per_field_and_owner(db):
    client, field = _client_with_vin(db)
    db.add(CustomValue(field_id=field.id, client_id=client.id, value_text="dup"))
    with pytest.raises(IntegrityError):
        db.commit()
