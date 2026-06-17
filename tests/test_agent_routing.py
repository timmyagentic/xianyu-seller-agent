from XianyuAgent import BaseAgent, IntentRouter, PriceAgent, TechAgent, XianyuReplyBot


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


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)

        class FakeMessage:
            content = "模型回复"

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]

        return FakeResponse()


class FakeClient:
    def __init__(self):
        self.completions = FakeCompletions()

        class Chat:
            pass

        self.chat = Chat()
        self.chat.completions = self.completions


class FakeNoChoicesCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)

        class FakeResponse:
            choices = None

            def model_dump(self):
                return {"choices": None, "object": "chat.completion"}

        return FakeResponse()


class FakeNoChoicesClient:
    def __init__(self):
        self.completions = FakeNoChoicesCompletions()

        class Chat:
            pass

        self.chat = Chat()
        self.chat.completions = self.completions


def test_intent_router_prioritizes_tech_before_price():
    router = IntentRouter(FakeClassifyAgent("default"))

    assert router.detect("这个型号和新版比有什么参数差异，价格能少吗", "商品", "") == "tech"


def test_base_agent_uses_modelscope_default_model(monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    client = FakeClient()
    agent = BaseAgent(client, "系统提示", lambda text: text)

    assert agent.generate("你好", "商品信息", "") == "模型回复"
    assert client.completions.calls[0]["model"] == "deepseek-ai/DeepSeek-V4-Pro"


def test_base_agent_adds_fact_constraints_to_prompt():
    client = FakeClient()
    agent = BaseAgent(client, "系统提示", lambda text: text)

    agent.generate("还有不", '{"total_stock": null}', "")

    system_prompt = client.completions.calls[0]["messages"][0]["content"]
    assert "事实约束" in system_prompt
    assert "库存为 null、unknown 或缺失时，只表示未知" in system_prompt
    assert "绝不能回复有优惠、折扣或赠品" in system_prompt


def test_base_agent_allows_model_name_override(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "custom/model")
    client = FakeClient()
    agent = BaseAgent(client, "系统提示", lambda text: text)

    agent.generate("你好", "商品信息", "")

    assert client.completions.calls[0]["model"] == "custom/model"


def test_price_agent_uses_modelscope_default_model(monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    client = FakeClient()
    agent = PriceAgent(client, "系统提示", lambda text: text)

    agent.generate("便宜点", "商品信息", "", bargain_count=2)

    assert client.completions.calls[0]["model"] == "deepseek-ai/DeepSeek-V4-Pro"


def test_tech_agent_omits_search_extension_by_default(monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("LLM_ENABLE_SEARCH", raising=False)
    client = FakeClient()
    agent = TechAgent(client, "系统提示", lambda text: text)

    agent.generate("参数怎么样", "商品信息", "")

    assert client.completions.calls[0]["model"] == "deepseek-ai/DeepSeek-V4-Pro"
    assert "extra_body" not in client.completions.calls[0]


def test_intent_router_detects_price_without_llm():
    classifier = FakeClassifyAgent("default")
    router = IntentRouter(classifier)

    assert router.detect("能少 20 元吗", "商品", "") == "price"
    assert classifier.calls == []


def test_intent_router_detects_common_discount_phrases_without_llm():
    classifier = FakeClassifyAgent("default")
    router = IntentRouter(classifier)

    for message in [
        "能优惠一点吗",
        "有折扣吗",
        "预算不够",
        "能刀吗",
        "学生党可以便宜吗",
        "最低多少",
        "能少一点吗",
        "再低点可以吗",
        "能让一点吗",
        "打折吗",
    ]:
        assert router.detect(message, "商品", "") == "price"
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


def test_reply_bot_refuses_discount_by_default_without_calling_price_agent(monkeypatch):
    monkeypatch.delenv("NO_BARGAIN_MODE", raising=False)
    bot = XianyuReplyBot.__new__(XianyuReplyBot)
    bot.router = FakeRouter("price")
    bot.agents = {
        "classify": FakeReplyAgent("unused"),
        "price": FakeReplyAgent("最低 10 元"),
        "tech": FakeReplyAgent("tech"),
        "default": FakeReplyAgent("default"),
    }
    bot.last_intent = None

    reply = bot.generate_reply("能便宜点吗，我马上拍", "商品信息", [])

    assert reply == "这个价格不议，当前标价就是最终价格。如能接受，可以直接拍。"
    assert bot.last_intent == "price"
    assert bot.agents["price"].calls == []


def test_reply_bot_does_not_refuse_plain_price_questions_by_default(monkeypatch):
    monkeypatch.delenv("NO_BARGAIN_MODE", raising=False)
    bot = XianyuReplyBot.__new__(XianyuReplyBot)
    bot.router = FakeRouter("price")
    bot.agents = {
        "classify": FakeReplyAgent("unused"),
        "price": FakeReplyAgent("标价 99 元"),
        "tech": FakeReplyAgent("tech"),
        "default": FakeReplyAgent("default"),
    }
    bot.last_intent = None

    for message in ["价格是多少？", "原价多少？"]:
        bot.agents["price"].calls.clear()

        reply = bot.generate_reply(message, "商品信息", [])

        assert reply == "标价 99 元"
        assert bot.last_intent == "price"
        assert bot.agents["price"].calls


def test_reply_bot_generate_reply_uses_router_and_bargain_count(monkeypatch):
    monkeypatch.setenv("NO_BARGAIN_MODE", "false")
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


def test_reply_bot_returns_fallback_when_reply_llm_has_no_choices():
    bot = XianyuReplyBot.__new__(XianyuReplyBot)
    bot.router = FakeRouter("tech")
    client = FakeNoChoicesClient()
    bot.agents = {
        "classify": FakeReplyAgent("unused"),
        "price": FakeReplyAgent("price"),
        "tech": TechAgent(client, "系统提示", lambda text: text),
        "default": FakeReplyAgent("default"),
    }
    bot.last_intent = None

    assert bot.generate_reply("这个可以用 GLM 5.2 吗", "商品信息", []) == "这个我确认一下，稍后回复你"
    assert bot.last_intent == "tech"
