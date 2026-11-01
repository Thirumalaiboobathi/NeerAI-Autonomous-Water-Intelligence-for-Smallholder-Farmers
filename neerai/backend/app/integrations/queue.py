"""Job queue adapters. Messages carry only ids (no farmer data): {"owner", "job_id", "correlation_id"}."""
from __future__ import annotations

import json
import threading
from typing import Callable, Protocol


class JobQueue(Protocol):
    def send(self, owner: str, job_id: str, correlation_id: str) -> None: ...


class SqsQueue:
    def __init__(self, queue_url: str, region: str, client=None):
        import boto3

        self.url = queue_url
        self.client = client or boto3.client("sqs", region_name=region)

    def send(self, owner: str, job_id: str, correlation_id: str) -> None:
        self.client.send_message(QueueUrl=self.url, MessageBody=json.dumps({"owner": owner, "job_id": job_id, "correlation_id": correlation_id}))


class InlineQueue:
    """Local/dev adapter: runs the same processor in a background thread of the API process (no AWS needed)."""

    def __init__(self, handler: Callable[[dict], None]):
        self.handler = handler

    def send(self, owner: str, job_id: str, correlation_id: str) -> None:
        msg = {"owner": owner, "job_id": job_id, "correlation_id": correlation_id}
        threading.Thread(target=self.handler, args=(msg,), daemon=True, name=f"job-{job_id}").start()
