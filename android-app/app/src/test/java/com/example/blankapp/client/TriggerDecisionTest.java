package com.example.blankapp.client;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class TriggerDecisionTest {

    @Test
    public void parseCleanJson() {
        String raw = "{\"shouldSpeak\": true, \"topicHint\": \"问候早安\", \"confidence\": 0.85}";
        TriggerDecision d = TriggerDecision.fromJson(raw);
        assertTrue(d.shouldSpeak);
        assertEquals("问候早安", d.topicHint);
        assertEquals(0.85f, d.confidence, 0.01);
    }

    @Test
    public void parseMarkdownFencedJson() {
        String raw = "```json\n{\"shouldSpeak\": true, \"topicHint\": \"问候\", \"confidence\": 0.7}\n```";
        TriggerDecision d = TriggerDecision.fromJson(raw);
        assertTrue(d.shouldSpeak);
        assertEquals("问候", d.topicHint);
    }

    @Test
    public void parseJsonWithLeadingNoise() {
        String raw = "好的，这是决策结果：\n{\"shouldSpeak\": false, \"topicHint\": null, \"confidence\": 0.0}";
        TriggerDecision d = TriggerDecision.fromJson(raw);
        assertFalse(d.shouldSpeak);
        assertNull(d.topicHint);
    }

    @Test
    public void parseLiteralNullTopicHint() {
        String raw = "{\"shouldSpeak\": true, \"topicHint\": null, \"confidence\": 0.5}";
        TriggerDecision d = TriggerDecision.fromJson(raw);
        assertTrue(d.shouldSpeak);
        assertNull("topicHint should be null when JSON value is null", d.topicHint);
    }

    @Test
    public void parseStringNullTopicHint() {
        // LLM sometimes returns "null" as a string
        String raw = "{\"shouldSpeak\": true, \"topicHint\": \"null\", \"confidence\": 0.5}";
        TriggerDecision d = TriggerDecision.fromJson(raw);
        assertTrue(d.shouldSpeak);
        assertNull("topicHint should be null when value is the string 'null'", d.topicHint);
    }

    @Test
    public void parseEmptyInput() {
        TriggerDecision d = TriggerDecision.fromJson("");
        assertFalse(d.shouldSpeak);
    }

    @Test
    public void parseNullInput() {
        TriggerDecision d = TriggerDecision.fromJson(null);
        assertFalse(d.shouldSpeak);
    }

    @Test
    public void parseNoAction() {
        TriggerDecision d = TriggerDecision.noAction();
        assertFalse(d.shouldSpeak);
        assertNull(d.topicHint);
        assertEquals(0f, d.confidence, 0.01);
    }

    @Test
    public void parseNoMarkdownCodeFence() {
        // Just ``` without language tag
        String raw = "```\n{\"shouldSpeak\": true, \"topicHint\": \"测试\", \"confidence\": 0.9}\n```";
        TriggerDecision d = TriggerDecision.fromJson(raw);
        assertTrue(d.shouldSpeak);
        assertEquals("测试", d.topicHint);
    }

    @Test
    public void parseShouldSpeakFalse() {
        String raw = "{\"shouldSpeak\": false, \"topicHint\": null, \"confidence\": 0.0}";
        TriggerDecision d = TriggerDecision.fromJson(raw);
        assertFalse(d.shouldSpeak);
        assertNull(d.topicHint);
    }

    @Test
    public void extractJsonObject_basic() {
        String s = TriggerDecision.extractJsonObject("{\"a\":1}");
        assertEquals("{\"a\":1}", s);
    }

    @Test
    public void extractJsonObject_withNoise() {
        String s = TriggerDecision.extractJsonObject("前言文字 {\"a\":1} 后语");
        assertEquals("{\"a\":1}", s);
    }
}
