from app.core.logging import redact
from app.repositories.base import FARM, Store
from app.repositories.dynamo import DynamoRepository
from app.repositories.sql import SqlRepository
from app.schemas.domain import Farm


class StubTable:
    """Minimal in-memory stand-in for a boto3 DynamoDB Table."""

    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = Item

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it else {}

    def delete_item(self, Key):
        self.items.pop((Key["pk"], Key["sk"]), None)

    def query(self, KeyConditionExpression=None, FilterExpression=None, Select=None, **kw):
        items = [v for (pk, _), v in self.items.items() if pk == "farm"]
        if Select == "COUNT":
            return {"Count": len(items)}
        return {"Items": items}


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


def test_dynamo_repository_with_stub_table():
    exercise(Store(DynamoRepository("t", table=StubTable())))


def test_redaction_of_secrets_and_pii():
    t = redact("key AKIAABCDEFGHIJKLMNOP token=abc123 Bearer eyJhbGci.x.y mail a.b@c.com phone 9876543210 api_key: s3cr3t")
    for leak in ["AKIAABCDEFGHIJKLMNOP", "abc123", "eyJhbGci", "a.b@c.com", "9876543210", "s3cr3t"]:
        assert leak not in t
    assert "REDACTED" in t


def test_redaction_leaves_agricultural_numbers_alone():
    assert redact("allocated 700,000 L of 1161538 L; rain 60%") == "allocated 700,000 L of 1161538 L; rain 60%"
