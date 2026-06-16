from collections import OrderedDict


class MessageDeduplicator:
    def __init__(self, max_size: int = 10_000):
        self.max_size = max_size
        self._seen: OrderedDict[str, None] = OrderedDict()

    def mark_seen(self, message_id: str | None) -> bool:
        """Return True when the message id has already been seen."""
        if not message_id:
            return False
        if message_id in self._seen:
            self._seen.move_to_end(message_id)
            return True
        self._seen[message_id] = None
        while len(self._seen) > self.max_size:
            self._seen.popitem(last=False)
        return False
