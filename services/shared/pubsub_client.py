from __future__ import annotations

import json

from google.cloud import pubsub_v1


class PubSubPublisher:
    def __init__(self, project_id: str):
        self.publisher = pubsub_v1.PublisherClient()
        self.project_id = project_id

    def publish_json(self, topic_name: str, payload: dict) -> str:
        topic_path = self.publisher.topic_path(self.project_id, topic_name)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        future = self.publisher.publish(topic_path, body)
        return future.result(timeout=30)


class PubSubSubscriber:
    def __init__(self, project_id: str):
        self.subscriber = pubsub_v1.SubscriberClient()
        self.project_id = project_id

    def pull(self, subscription_name: str, max_messages: int) -> list[pubsub_v1.types.ReceivedMessage]:
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
