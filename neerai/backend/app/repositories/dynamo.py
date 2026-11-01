"""DynamoDB repository (AWS mode). Single table, per-user partitions.

Key design (schema version 2, attribute `v`):
  pk = "USER#<owner>"            one partition per authenticated user -> tenant isolation is part of the key
  sk = "<kind>#<id>"             kind in {farm, field, plan, scenario, execution, job, audit}
Access patterns (none uses a Scan):
  get/put/delete one record        GetItem/PutItem/DeleteItem (pk, sk)
  list a user's records of a kind  Query pk = USER#x AND begins_with(sk, "<kind>#"), optional filter on `parent`
  count a user's records of a kind Query ... Select=COUNT
  idempotent create / state change PutItem with ConditionExpression (attribute_not_exists / version = :v)
`ttl` (epoch seconds) is set on temporary records (jobs); the table has TTL enabled on that attribute.
A user's partition is small (tens of farms/fields, bounded plans/jobs), so the filter on `parent` does not read much.
Migration: bump `v`, write new item shapes alongside old ones, read tolerantly; never rewrite in place without a backup (PITR is on).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel

SCHEMA_VERSION = 2
LOCAL_OWNER = "local"


def _pk(owner: str) -> str:
    return f"USER#{owner}"


class DynamoRepository:
    def __init__(self, table_name: str, table: Any = None, region: Optional[str] = None):
        if table is None:
            import boto3

            table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self.table = table

    @staticmethod
    def _item(kind: str, id: str, doc: BaseModel, parent: Optional[str], owner: str, ttl_seconds: Optional[int]) -> dict:
        item: dict = {"pk": _pk(owner), "sk": f"{kind}#{id}", "kind": kind, "body": doc.model_dump_json(), "v": SCHEMA_VERSION,
                      "version": int(getattr(doc, "version", 0) or 0), "created_at": datetime.now(timezone.utc).isoformat()}
        if parent:
            item["parent"] = parent
        if ttl_seconds:
            item["ttl"] = int(time.time()) + ttl_seconds
        return item

    def put(self, kind: str, id: str, doc: BaseModel, parent: Optional[str] = None, *, owner: str = LOCAL_OWNER,
            ttl_seconds: Optional[int] = None) -> None:
        self.table.put_item(Item=self._item(kind, id, doc, parent, owner, ttl_seconds))

    def put_conditional(self, kind: str, id: str, doc: BaseModel, parent: Optional[str] = None, *, owner: str = LOCAL_OWNER,
                        ttl_seconds: Optional[int] = None, if_absent: bool = False, expect_version: Optional[int] = None) -> bool:
        kwargs: dict = {"Item": self._item(kind, id, doc, parent, owner, ttl_seconds)}
        if if_absent:
            kwargs["ConditionExpression"] = "attribute_not_exists(pk)"
        elif expect_version is not None:
            kwargs["ConditionExpression"] = "#ver = :v"
            kwargs["ExpressionAttributeNames"] = {"#ver": "version"}
            kwargs["ExpressionAttributeValues"] = {":v": expect_version}
        try:
            self.table.put_item(**kwargs)
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def get_raw(self, kind: str, id: str, *, owner: str = LOCAL_OWNER) -> Optional[str]:
        r = self.table.get_item(Key={"pk": _pk(owner), "sk": f"{kind}#{id}"})
        item = r.get("Item")
        if not item or int(item.get("ttl", 0) or 0) and int(item["ttl"]) < time.time():
            return None  # TTL deletion is lazy (up to ~48h); treat expired items as gone
        return item.get("body")

    def list_raw(self, kind: str, parent: Optional[str] = None, limit: int = 500, *, owner: str = LOCAL_OWNER) -> list[str]:
        from boto3.dynamodb.conditions import Attr, Key

        kwargs: dict = {"KeyConditionExpression": Key("pk").eq(_pk(owner)) & Key("sk").begins_with(f"{kind}#")}
        if parent is not None:
            kwargs["FilterExpression"] = Attr("parent").eq(parent)
        items: list[dict] = []
        now = time.time()
        while True:
            r = self.table.query(**kwargs)
            items += [i for i in r.get("Items", []) if not (i.get("ttl") and int(i["ttl"]) < now)]
            if "LastEvaluatedKey" not in r or len(items) >= limit * 4:
                break
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        items.sort(key=lambda i: i.get("created_at", ""), reverse=True)
        return [i["body"] for i in items[:limit]]

    def delete(self, kind: str, id: str, *, owner: str = LOCAL_OWNER) -> None:
        self.table.delete_item(Key={"pk": _pk(owner), "sk": f"{kind}#{id}"})

    def count(self, kind: str, *, owner: str = LOCAL_OWNER) -> int:
        from boto3.dynamodb.conditions import Key

        total, kwargs = 0, {"KeyConditionExpression": Key("pk").eq(_pk(owner)) & Key("sk").begins_with(f"{kind}#"), "Select": "COUNT"}
        while True:
            r = self.table.query(**kwargs)
            total += int(r.get("Count", 0))
            if "LastEvaluatedKey" not in r:
                return total
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
