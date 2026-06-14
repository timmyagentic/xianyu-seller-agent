from XianyuAgent import IntentRouter, XianyuReplyBot


class FakeClassifyAgent:
    def __init__(self, intent="default"):
        self.intent = intent
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.intent


class FakeReplyAgent:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


class FakeRouter:
    def __init__(self, intent):
        self.intent = intent
        self.calls = []

    def detect(self, user_msg, item_desc, context):
        self.calls.append((user_msg, item_desc, context))
        return self.intent


def test_intent_router_prioritizes_tech_before_price():
    router = IntentRouter(FakeClassifyAgent("default"))

    assert router.detect("这个型号和新版比有什么参数差异，价格能少吗", "商品", "") == "tech"


def test_intent_router_detects_price_without_llm():
    classifier = FakeClassifyAgent("default")
    router = IntentRouter(classifier)

    assert router.detect("能少 20 元吗", "商品", "") == "price"
    assert classifier.calls == []


def test_intent_router_falls_back_to_classifier():
    classifier = FakeClassifyAgent("no_reply")
    router = IntentRouter(classifier)

    assert router.detect("谢谢，我再看看", "商品", "user: hi") == "no_reply"
    assert classifier.calls[0]["user_msg"] == "谢谢，我再看看"


def test_reply_bot_safe_filter_blocks_off_platform_terms():
    bot = XianyuReplyBot.__new__(XianyuReplyBot)

    assert bot._safe_filter("可以加微信聊") == "[安全提醒]请通过平台沟通"
    assert bot._safe_filter("平台内沟通即可") == "平台内沟通即可"


def test_reply_bot_generate_reply_uses_router_and_bargain_count():
    bot = XianyuReplyBot.__new__(XianyuReplyBot)
    bot.router = FakeRouter("price")
    bot.agents = {
        "classify": FakeReplyAgent("unused"),
        "price": FakeReplyAgent("最低 10 元"),
        "tech": FakeReplyAgent("tech"),
        "default": FakeReplyAgent("default"),
    }
    bot.last_intent = None

    reply = bot.generate_reply(
        "便宜点",
        "商品信息",
        [
            {"role": "user", "content": "便宜点"},
            {"role": "system", "content": "议价次数: 3"},
        ],
    )

    assert reply == "最低 10 元"
    assert bot.last_intent == "price"
    assert bot.agents["price"].calls[0]["bargain_count"] == 3


def test_reply_bot_returns_marker_for_no_reply_intent():
    bot = XianyuReplyBot.__new__(XianyuReplyBot)
    bot.router = FakeRouter("no_reply")
    bot.agents = {
        "classify": FakeReplyAgent("unused"),
        "price": FakeReplyAgent("price"),
        "tech": FakeReplyAgent("tech"),
        "default": FakeReplyAgent("default"),
    }
    bot.last_intent = None

    assert bot.generate_reply("谢谢", "商品信息", []) == "-"
    assert bot.last_intent == "no_reply"
