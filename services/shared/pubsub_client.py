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
