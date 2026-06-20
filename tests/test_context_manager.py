import sqlite3

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


def test_context_manager_records_message_source(tmp_path):
    db_path = tmp_path / "chat_history.db"
    manager = ChatContextManager(max_history=5, db_path=str(db_path))

    manager.add_message_by_chat("chat-1", "buyer-1", "item-1", "user", "体验结束能续费吗")
    manager.add_message_by_chat("chat-1", "seller-1", "item-1", "assistant", "不能", source="manual")
    manager.add_message_by_chat("chat-2", "seller-1", "item-1", "assistant", "自动回复", source="bot")

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT chat_id, role, content, source FROM messages ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("chat-1", "user", "体验结束能续费吗", "user"),
        ("chat-1", "assistant", "不能", "manual"),
        ("chat-2", "assistant", "自动回复", "bot"),
    ]


def test_context_manager_lists_manual_replies_by_source(tmp_path):
    manager = ChatContextManager(max_history=5, db_path=str(tmp_path / "chat_history.db"))

    manager.add_message_by_chat("chat-1", "buyer-1", "item-1", "user", "自己的账号用吗")
    manager.add_message_by_chat("chat-1", "seller-1", "item-1", "assistant", "是的没错", source="manual")
    manager.add_message_by_chat("chat-1", "seller-1", "item-1", "assistant", "这个我确认一下", source="bot")

    assert manager.get_messages_by_source("manual") == [
        {
            "chat_id": "chat-1",
            "user_id": "seller-1",
            "item_id": "item-1",
            "role": "assistant",
            "content": "是的没错",
            "source": "manual",
        }
    ]


def test_context_manager_migrates_existing_messages_with_source(tmp_path):
    db_path = tmp_path / "chat_history.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                chat_id TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO messages (user_id, item_id, role, content, chat_id)
            VALUES ('buyer-1', 'item-1', 'user', '5.2能用吗', 'chat-1')
            """
        )
        conn.execute(
            """
            INSERT INTO messages (user_id, item_id, role, content, chat_id)
            VALUES ('seller-1', 'item-1', 'assistant', '不能用', 'chat-1')
            """
        )
        conn.commit()
    finally:
        conn.close()

    ChatContextManager(db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT role, content, source FROM messages ORDER BY id").fetchall()
    finally:
        conn.close()

    assert rows == [
        ("user", "5.2能用吗", "user"),
        ("assistant", "不能用", "unknown"),
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
