from context_manager import ChatContextManager


def test_context_manager_persists_item_and_chat_history(tmp_path):
    db_path = tmp_path / "chat_history.db"
    manager = ChatContextManager(max_history=5, db_path=str(db_path))

    item = {"itemId": "item-1", "soldPrice": "12.50", "desc": "download code"}
    manager.save_item_info("item-1", item)
    manager.add_message_by_chat("chat-1", "buyer-1", "item-1", "user", "还在吗")
    manager.add_message_by_chat("chat-1", "seller-1", "item-1", "assistant", "在的")

    assert manager.get_item_info("item-1") == item
    assert manager.get_context_by_chat("chat-1") == [
        {"role": "user", "content": "还在吗"},
        {"role": "assistant", "content": "在的"},
    ]


def test_context_manager_tracks_bargain_count_in_context(tmp_path):
    manager = ChatContextManager(db_path=str(tmp_path / "chat_history.db"))
    manager.add_message_by_chat("chat-1", "buyer-1", "item-1", "user", "便宜点")

    manager.increment_bargain_count_by_chat("chat-1")
    manager.increment_bargain_count_by_chat("chat-1")

    assert manager.get_bargain_count_by_chat("chat-1") == 2
    assert manager.get_context_by_chat("chat-1")[-1] == {
        "role": "system",
        "content": "议价次数: 2",
    }


def test_context_manager_limits_history_by_chat_id(tmp_path):
    manager = ChatContextManager(max_history=2, db_path=str(tmp_path / "chat_history.db"))

    manager.add_message_by_chat("chat-1", "buyer-1", "item-1", "user", "1")
    manager.add_message_by_chat("chat-1", "seller-1", "item-1", "assistant", "2")
    manager.add_message_by_chat("chat-1", "buyer-1", "item-1", "user", "3")

    assert manager.get_context_by_chat("chat-1") == [
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
    ]
