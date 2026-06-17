import json

from services.messages.knowledge import (
    ItemKnowledgeBase,
    UnknownQuestionLog,
    looks_like_unknown_reply,
)


def test_item_knowledge_base_reads_item_markdown_for_prompt(tmp_path):
    knowledge_dir = tmp_path / "item_knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "item-1.md").write_text(
        "# 智谱 GLM coding plan\n\n"
        "## 常见问题\n"
        "- token 限制：参考官方 Lite 计划。\n"
        "- 额外费用：没有其他费用。\n",
        encoding="utf-8",
    )
    base = ItemKnowledgeBase(root_dir=knowledge_dir)

    prompt_context = base.format_for_prompt("item-1")

    assert "【商品知识库】" in prompt_context
    assert "智谱 GLM coding plan" in prompt_context
    assert "token 限制：参考官方 Lite 计划" in prompt_context
    assert "知识库或商品信息没有明确写到" in prompt_context


def test_item_knowledge_base_returns_empty_for_missing_item(tmp_path):
    base = ItemKnowledgeBase(root_dir=tmp_path / "item_knowledge")

    assert base.read("item-missing") == ""
    assert base.format_for_prompt("item-missing") == ""


def test_unknown_question_log_appends_jsonl(tmp_path):
    log_path = tmp_path / "unknown_questions.jsonl"
    log = UnknownQuestionLog(path=log_path)

    log.append(
        item_id="item-1",
        chat_id="chat-1",
        question="在哪兑换",
        reason="fallback_reply",
        reply="这个我确认一下，稍后回复你",
        intent="default",
    )

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["item_id"] == "item-1"
    assert rows[0]["chat_id"] == "chat-1"
    assert rows[0]["question"] == "在哪兑换"
    assert rows[0]["reason"] == "fallback_reply"
    assert rows[0]["reply"] == "这个我确认一下，稍后回复你"
    assert rows[0]["intent"] == "default"
    assert rows[0]["created_at"]


def test_unknown_reply_detector_matches_uncertain_seller_replies():
    assert looks_like_unknown_reply("这个我确认一下，稍后回复你") is True
    assert looks_like_unknown_reply("我先核实一下再回复你") is True
    assert looks_like_unknown_reply("这个帮你确认下") is True
    assert looks_like_unknown_reply("不太确定，我问一下") is True
    assert looks_like_unknown_reply("有的，拍下就行") is False
