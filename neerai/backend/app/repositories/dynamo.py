"""DynamoDB repository (AWS mode). Single table: PK = kind, SK = id; `parent` and `created_at` stored as attributes.

Note: written against the boto3 resource API and unit-tested with a stub table; not verified against a live AWS account
in this repository (see docs/SUBMISSION_CHECKLIST.md).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel


class DynamoRepository:
    def __init__(self, table_name: str, table: Any = None, region: Optional[str] = None):
        if table is None:
            import boto3

            table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self.table = table

    def put(self, kind: str, id: str, doc: BaseModel, parent: Optional[str] = None) -> None:
        item = {"pk": kind, "sk": id, "body": doc.model_dump_json(), "created_at": datetime.now(timezone.utc).isoformat()}
        if parent:
            item["parent"] = parent
        self.table.put_item(Item=item)

    def get_raw(self, kind: str, id: str) -> Optional[str]:
        r = self.table.get_item(Key={"pk": kind, "sk": id})
        return r.get("Item", {}).get("body")

    def list_raw(self, kind: str, parent: Optional[str] = None, limit: int = 500) -> list[str]:
        from boto3.dynamodb.conditions import Attr, Key

        kwargs: dict = {"KeyConditionExpression": Key("pk").eq(kind)}
        if parent is not None:
            kwargs["FilterExpression"] = Attr("parent").eq(parent)
        items: list[dict] = []
        while True:
            r = self.table.query(**kwargs)
            items += r.get("Items", [])
            if "LastEvaluatedKey" not in r or len(items) >= limit * 4:
                break
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        items.sort(key=lambda i: i.get("created_at", ""), reverse=True)
        return [i["body"] for i in items[:limit]]

    def delete(self, kind: str, id: str) -> None:
        self.table.delete_item(Key={"pk": kind, "sk": id})

    def count(self, kind: str) -> int:
        from boto3.dynamodb.conditions import Key

        r = self.table.query(KeyConditionExpression=Key("pk").eq(kind), Select="COUNT")
        return int(r.get("Count", 0))
