from app.core.logging import redact
from app.repositories.base import FARM, Store
from app.repositories.sql import SqlRepository
from app.schemas.domain import Farm


def exercise(store: Store):
    a, b = Farm(farm_name="A"), Farm(farm_name="B")
    store.save(FARM, a)
    store.save(FARM, b)
    assert store.count(FARM) == 2
    assert store.get(FARM, a.id, Farm).farm_name == "A"
    a.farm_name = "A2"
    store.save(FARM, a)
    assert store.get(FARM, a.id, Farm).farm_name == "A2" and store.count(FARM) == 2
    store.delete(FARM, b.id)
    assert store.get(FARM, b.id, Farm) is None and store.count(FARM) == 1


def test_sql_repository():
    exercise(Store(SqlRepository("sqlite://")))


def test_sql_parent_filter():
    s = Store(SqlRepository("sqlite://"))
    s.save(FARM, Farm(farm_name="x"), parent="p1")
    s.save(FARM, Farm(farm_name="y"), parent="p2")
    assert [f.farm_name for f in s.list(FARM, Farm, parent="p1")] == ["x"]
