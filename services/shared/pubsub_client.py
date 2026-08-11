from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from services.shared.config import RuntimeConfig


class MessagePublisher(Protocol):
    def publish_json(self, topic_name: str, payload: dict[str, Any]) -> str: ...


class PubSubPublisher:
    def __init__(self, project_id: str):
        from google.cloud import pubsub_v1

        self.publisher = pubsub_v1.PublisherClient()
        self.project_id = project_id

    def publish_json(self, topic_name: str, payload: dict[str, Any]) -> str:
        topic_path = self.publisher.topic_path(self.project_id, topic_name)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        future = self.publisher.publish(topic_path, body)
        return future.result(timeout=30)


class PubSubSubscriber:
    def __init__(self, project_id: str):
        from google.cloud import pubsub_v1

        self._pubsub_v1 = pubsub_v1
        self.subscriber = pubsub_v1.SubscriberClient()
        self.project_id = project_id

    def pull(self, subscription_name: str, max_messages: int) -> list[Any]:
        subscription_path = self.subscriber.subscription_path(self.project_id, subscription_name)
        response = self.subscriber.pull(
            request={"subscription": subscription_path, "max_messages": max_messages},
            timeout=30,
        )
        return list(response.received_messages)

    def acknowledge(self, subscription_name: str, ack_ids: list[str]) -> None:
        if not ack_ids:
            return
        subscription_path = self.subscriber.subscription_path(self.project_id, subscription_name)
        self.subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": ack_ids})


class DirectProcessorPublisher:
    """Local queue adapter: submit the existing ingest contract directly over HTTP."""

    def __init__(self, *, processor_url: str, bearer_token: str, ingest_topic: str, timeout_seconds: int = 120):
        self._url = processor_url.rstrip("/") + "/v1/process"
        self._bearer_token = bearer_token
        self._ingest_topic = ingest_topic
        self._timeout_seconds = timeout_seconds

    def publish_json(self, topic_name: str, payload: dict[str, Any]) -> str:
        if topic_name != self._ingest_topic:
            raise RuntimeError("Direct queue adapter does not provide a local DLQ")
        headers = {"Content-Type": "application/json"}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        request = Request(
            self._url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                if response.status >= 400:
                    raise RuntimeError(f"Processor rejected local ingest with HTTP {response.status}")
        except HTTPError as exc:
            raise RuntimeError(f"Processor rejected local ingest with HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError("Local processor is unavailable") from exc
        return f"direct:{payload.get('id', 'unknown')}"


def build_publisher(config: RuntimeConfig) -> MessagePublisher:
    if config.queue_backend == "direct_http":
        return DirectProcessorPublisher(
            processor_url=config.processor_url,
            bearer_token=config.local_auth_token,
            ingest_topic=config.ingest_topic,
        )
    if config.queue_backend == "pubsub":
        return PubSubPublisher(config.project_id)
    raise RuntimeError(f"Unsupported queue backend: {config.queue_backend}")


def build_subscriber(config: RuntimeConfig) -> PubSubSubscriber | None:
    if config.queue_backend == "pubsub":
        return PubSubSubscriber(config.project_id)
    return None
