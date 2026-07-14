from app.sessions import SessionManager


def test_sqlite_session_context_roundtrip(tmp_path):
    db_path = tmp_path / "companion_test.db"
    sm = SessionManager(db_path=str(db_path))

    session_id = sm.get_or_create_session("u1", contact_id="c1")
    sm.append_message(session_id, "user", "你好")
    sm.append_message(session_id, "assistant", "你好呀")

    history = sm.get_context(session_id, limit=10)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert sm.count_messages(session_id) == 2



def test_sqlite_memory_upsert_and_get(tmp_path):
    db_path = tmp_path / "companion_test.db"
    sm = SessionManager(db_path=str(db_path))

    sm.upsert_memory(
        user_id="u1",
        contact_id="c1",
        memory={
            "summary": "用户最近在备考",
            "timeline": [{"date": "07-14", "topic": "准备考试", "notes": "有些焦虑"}],
            "facts": ["喜欢咖啡"],
            "patterns": "晚上更容易打开话题",
            "schema_version": "1.0",
            "working_memory": [{"role": "user", "content": "我在复习"}],
            "episodic_memory": [{"date": "07-14", "topic": "exam"}],
            "semantic_memory": {"summary": "备考中", "facts": ["喜欢咖啡"], "patterns": "晚间活跃"},
            "meta": {"last_reason_code": "rule_pass"},
        },
    )

    memory = sm.get_memory("u1", contact_id="c1")
    assert memory["summary"] == "用户最近在备考"
    assert memory["facts"] == ["喜欢咖啡"]
    assert memory["schema_version"] == "1.0"
    assert memory["working_memory"][0]["role"] == "user"
    assert memory["meta"]["last_reason_code"] == "rule_pass"
    assert memory["updated_at"] is not None
