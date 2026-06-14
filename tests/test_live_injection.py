import inspect
import asyncio
import json

from main import XianyuLive


def test_xianyu_live_accepts_reply_bot_injection():
    signature = inspect.signature(XianyuLive)

    assert "reply_bot" in signature.parameters


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))


def test_xianyu_live_marks_incoming_message_as_read():
    live = XianyuLive.__new__(XianyuLive)
    websocket = FakeWebSocket()

    asyncio.run(live.mark_message_read(websocket, "chat-1", "msg-1"))

    assert websocket.sent[0]["lwp"] == "/r/Conversation/clearRedPoint"
    assert websocket.sent[0]["body"] == [[{"cid": "chat-1@goofish", "messageId": "msg-1"}]]
    assert websocket.sent[1]["lwp"] == "/r/MessageStatus/read"
    assert websocket.sent[1]["body"] == [["msg-1"]]
