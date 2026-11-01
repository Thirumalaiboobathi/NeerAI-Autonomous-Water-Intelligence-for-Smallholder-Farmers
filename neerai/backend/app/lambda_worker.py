"""AWS Lambda entrypoint for the SQS agent worker (event source mapping with ReportBatchItemFailures).

One message = one agent job (batch size 1). Per message:
* job reached a terminal state (or message is forged/unknown) -> success: SQS deletes the message
* transient failure                                           -> reported as a batch item failure; the message becomes visible again
                                                                 after an exponential-backoff delay, and SQS redrives it to the DLQ
                                                                 after `maxReceiveCount` receives
Concurrency of agent runs is capped by the event source mapping's maximum concurrency (set in CDK), not by reserved concurrency.
"""
from __future__ import annotations

import json
import logging
import random

from .core.config import get_settings
from .core.logging import configure_logging
from .main import build_repository
from .repositories.base import Store
from .services.jobs import JobProcessor
from .services.weather_service import WeatherService

log = logging.getLogger("neerai.worker")

_processor: JobProcessor | None = None
_sqs = None


def backoff_seconds(receive_count: int) -> int:
    """15 s, 30 s, 60 s ... capped at 5 min, with +/-30% jitter so retries do not synchronise."""
    return int(min(300, 15 * (2 ** max(0, receive_count - 1))) * random.uniform(0.7, 1.3))


def _get_processor() -> JobProcessor:
    global _processor
    if _processor is None:
        s = get_settings()
        configure_logging(s.log_level, s.log_format)
        s.validate_runtime("worker")
        _processor = JobProcessor(s, Store(build_repository(s)), WeatherService(s))
    return _processor


def _client():
    global _sqs
    if _sqs is None:
        import boto3

        _sqs = boto3.client("sqs", region_name=get_settings().aws_region)
    return _sqs


def handler(event: dict, context=None) -> dict:
    proc = _get_processor()
    failures: list[dict] = []
    for rec in event.get("Records", []):
        count = int(rec.get("attributes", {}).get("ApproximateReceiveCount", "1"))
        try:
            outcome = proc.process(json.loads(rec["body"]), count)
        except Exception as e:  # noqa: BLE001 - malformed/unexpected: leave for redelivery, ends in the DLQ
            log.error("message processing error: %s", type(e).__name__)
            outcome = "retry"
        if outcome == "retry":
            failures.append({"itemIdentifier": rec["messageId"]})
            try:  # shorten/lengthen the redelivery delay; best effort (needs sqs:ChangeMessageVisibility)
                _client().change_message_visibility(QueueUrl=proc.settings.jobs_queue_url, ReceiptHandle=rec["receiptHandle"],
                                                    VisibilityTimeout=backoff_seconds(count))
            except Exception as e:  # noqa: BLE001
                log.warning("could not adjust visibility: %s", type(e).__name__)
    return {"batchItemFailures": failures}
