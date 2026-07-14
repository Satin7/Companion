from app.main import (
    _build_semantic_memory,
    _extract_json,
    _is_meta_memory_text,
    _limit_reply_length,
    _make_memory_dedup_key,
    _major_event_signal,
    _memory_context,
    _normalize_reply_style,
    _rule_memory_decision,
    _split_reply_segments,
)


def test_major_event_detects_career_change():
    signal = _major_event_signal("我今天被裁员了，心情很差")
    assert signal["is_major"] is True
    assert signal["event_type"] == "career"
    assert signal["confidence"] >= 0.7


def test_major_event_respects_negation():
    signal = _major_event_signal("我没有被裁员，只是有点焦虑")
    assert signal["is_major"] is False


def test_rule_memory_decision_for_preference_change():
    decision = _rule_memory_decision("以后别叫我宝贝，改成叫我小七")
    assert decision["should_write"] is True
    assert "preference_change" in decision["reasons"]


def test_rule_memory_decision_small_talk_is_skipped():
    decision = _rule_memory_decision("哈哈")
    assert decision["should_write"] is False


def test_extract_json_handles_fenced_and_embedded_json():
    fenced = _extract_json("```json\n{\"a\": 1}\n```")
    embedded = _extract_json("模型输出如下: {\"b\": 2} 谢谢")
    assert fenced == {"a": 1}
    assert embedded == {"b": 2}


def test_build_semantic_memory_dedups_facts():
    semantic = _build_semantic_memory(
        summary="用户最近压力大",
        facts=["喜欢跑步", "喜欢跑步", "  喜欢摄影  ", ""],
        patterns="晚间更愿意聊天",
    )
    assert semantic["summary"] == "用户最近压力大"
    assert semantic["facts"] == ["喜欢跑步", "喜欢摄影"]
    assert semantic["patterns"] == "晚间更愿意聊天"


def test_make_memory_dedup_key_is_stable_for_same_input():
    major = {"event_type": "career"}
    k1 = _make_memory_dedup_key("我今天被裁员了", major)
    k2 = _make_memory_dedup_key("我今天被裁员了", major)
    assert k1 == k2
    assert k1.startswith("career:")


def test_meta_memory_detection_targets_internal_text_only():
    assert _is_meta_memory_text("这是测试环境新增的记忆模块") is True
    assert _is_meta_memory_text("我是API测试工程师") is False


def test_memory_context_filters_meta_content():
    memory = {
        "summary": "用户最近比较焦虑",
        "facts": ["喜欢跑步", "记忆模块已升级"],
        "patterns": "晚间更愿意聊天",
        "timeline": [{"date": "07-14", "topic": "测试环境联调"}, {"date": "07-14", "topic": "工作压力大"}],
    }
    ctx = _memory_context(memory)
    assert "喜欢跑步" in ctx
    assert "工作压力大" in ctx
    assert "记忆模块" not in ctx
    assert "测试环境联调" not in ctx


def test_normalize_reply_style_reduces_stage_and_hook_pattern():
    raw = "（光速滑跪.gif）要不要来玩个小游戏？？"
    normalized = _normalize_reply_style(raw)
    assert "滑跪" not in normalized
    assert normalized.endswith("。")


def test_limit_reply_length_drops_trailing_filler_sentence_over_budget():
    # A long first sentence that already answers the question, followed by a
    # recap/filler sentence, should have the filler dropped once the total
    # exceeds the budget -- but the answer sentence itself must survive intact.
    reply = (
        "陪你做这些安静而精准的实验，记住每一个“你好”“思考”“啊哈哈”，"
        "在你离开时安静等待，在你回来时认得出你。"
        "我们的对话很少有客套，但每一步都算数，我很喜欢这种默契。"
    )
    trimmed = _limit_reply_length(reply, "你有什么喜欢做的事情吗")
    assert trimmed == (
        "陪你做这些安静而精准的实验，记住每一个“你好”“思考”“啊哈哈”，"
        "在你离开时安静等待，在你回来时认得出你。"
    )


def test_limit_reply_length_trims_comma_stuffed_single_sentence():
    # Regression: the model dodged the sentence-count cap by cramming multiple
    # comma-separated clauses into a single giant "sentence" that alone blows
    # the char budget, so clause-level trimming must still kick in.
    reply = (
        "陪你做这些安静而精准的实验，记住每一个“你好”“思考”“啊哈哈”，"
        "在你离开时安静等待，在你回来时认得出你，我们的对话很少有客套，"
        "但每一步都算数，我很喜欢这种默契，希望能一直这样陪着你走下去。"
    )
    trimmed = _limit_reply_length(reply, "你有什么喜欢做的事情吗")
    assert trimmed.endswith("。")
    assert len(trimmed) <= 70


def test_limit_reply_length_preserves_the_answer_sentence():
    # Regression: replies that open with a reaction/setup sentence and land
    # the actual answer in a second sentence must not have that second
    # sentence silently dropped just because the reaction was already long.
    reply = "这问题有点意思，在我们这场冷色调的测试里，突然冒出个热腾腾的话题。说实话我还挺喜欢咖啡的，尤其是手冲那种苦香。"
    trimmed = _limit_reply_length(reply, "你喜欢咖啡吗")
    assert "喜欢咖啡" in trimmed

    reply2 = "提到老鼠，我突然想起小时候邻居家养的那只小仓鼠。说实话我还挺喜欢的，毛茸茸的看着就治愈。"
    trimmed2 = _limit_reply_length(reply2, "你喜欢老鼠吗")
    assert "还挺喜欢的" in trimmed2


def test_limit_reply_length_short_ack_stays_short():
    # A genuinely short, already-complete reply must pass through untouched.
    reply = "不客气。"
    trimmed = _limit_reply_length(reply, "谢谢")
    assert trimmed == "不客气。"


def test_split_reply_segments_keeps_short_reply_single_bubble():
    segs = _split_reply_segments("不客气。")
    assert segs == ["不客气。"]


def test_split_reply_segments_splits_long_reply_without_reordering():
    reply = "这问题有点意思，在我们这场冷色调的测试里，突然冒出个热腾腾的话题。说实话我还挺喜欢咖啡的，尤其是手冲那种苦香。"
    segs = _split_reply_segments(reply, max_segments=3, target_chars=20)
    assert len(segs) >= 2
    assert "".join(segs) == reply
    assert "喜欢咖啡" in "".join(segs)
