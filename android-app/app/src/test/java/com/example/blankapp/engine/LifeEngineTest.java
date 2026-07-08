package com.example.blankapp.engine;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import org.junit.Before;
import org.junit.Test;

public class LifeEngineTest {

    private LifeEngine engine;

    @Before
    public void setUp() {
        engine = new LifeEngine(null);
    }

    // ── interaction mode ────────────────────────────────────────

    @Test
    public void initialModeIsPresent() {
        assertEquals(LifeEngine.InteractionMode.PRESENT, engine.getInteractionMode());
    }

    @Test
    public void userMessage_keepsPresent() {
        engine.onUserMessage(System.currentTimeMillis());
        assertEquals(LifeEngine.InteractionMode.PRESENT, engine.getInteractionMode());
    }

    @Test
    public void silentBeyondThreshold_switchesToAbsent() {
        long now = System.currentTimeMillis();
        engine.setIdleThresholdMs(60_000L); // 1min test mode
        // Simulate: last message was 90s ago, then tick
        engine.onUserMessage(now - 90_000L);
        engine.onTimerTick(now);

        LifeEngineEvent event = engine.checkForLifeSignal(now);
        // After 90s > 1min threshold, should have switched to ABSENT
        assertEquals(LifeEngine.InteractionMode.ABSENT, engine.getInteractionMode());
    }

    @Test
    public void userMessageInAbsent_switchesBackToPresent() {
        // First go to ABSENT
        long now = System.currentTimeMillis();
        engine.setIdleThresholdMs(60_000L);
        engine.onUserMessage(now - 90_000L);
        engine.onTimerTick(now);
        engine.checkForLifeSignal(now);
        assertEquals(LifeEngine.InteractionMode.ABSENT, engine.getInteractionMode());

        // User sends message → back to PRESENT
        engine.onUserMessage(now + 1000L);
        assertEquals(LifeEngine.InteractionMode.PRESENT, engine.getInteractionMode());
    }

    // ── user message analysis ────────────────────────────────────

    @Test
    public void analyzesNeedCareWords() {
        engine.onUserMessage(System.currentTimeMillis(), "我今天很累，压力很大");
        assertEquals(0.8f, engine.getLastUserMsgNeedCare(), 0.1f); // 2 words × 0.4
        assertEquals(0.3f, engine.getLastUserMsgIntensity(), 0.1f); // 1 word × 0.3
    }

    @Test
    public void analyzesNeutralMessage() {
        engine.onUserMessage(System.currentTimeMillis(), "今天天气不错");
        assertEquals(0f, engine.getLastUserMsgNeedCare(), 0.01);
        assertEquals(0f, engine.getLastUserMsgIntensity(), 0.01);
    }

    @Test
    public void onUserMessageWithoutText_doesNotCrash() {
        engine.onUserMessage(System.currentTimeMillis()); // null text
        assertEquals(0f, engine.getLastUserMsgNeedCare(), 0.01);
    }

    // ── proactive tracking ──────────────────────────────────────

    @Test
    public void proactiveSent_incrementsNoReply() {
        assertEquals(0, engine.getConsecutiveNoReply());
        engine.onProactiveSent(System.currentTimeMillis());
        assertEquals(1, engine.getConsecutiveNoReply());
        engine.onProactiveSent(System.currentTimeMillis());
        assertEquals(2, engine.getConsecutiveNoReply());
    }

    @Test
    public void userMessage_resetsNoReply() {
        engine.onProactiveSent(System.currentTimeMillis());
        engine.onProactiveSent(System.currentTimeMillis());
        assertEquals(2, engine.getConsecutiveNoReply());

        engine.onUserMessage(System.currentTimeMillis(), "我回来了");
        assertEquals(0, engine.getConsecutiveNoReply());
    }

    // ── existing behavior still works ────────────────────────────

    @Test
    public void initialStateIsIdle() {
        assertNull(engine.checkForLifeSignal(System.currentTimeMillis()));
    }

    @Test
    public void freshContact_triggers() {
        long now = System.currentTimeMillis();
        engine.setIdleThresholdMs(100L);
        engine.onTimerTick(now + 200L);
        LifeEngineEvent event = engine.checkForLifeSignal(now + 200L);
        assertNotNull("Should trigger INITIAL_GREETING", event);
    }

    @Test
    public void persistAndLoad_withNullContext_doesNotCrash() {
        engine.onUserMessage(System.currentTimeMillis(), "你好");
        engine.onProactiveSent(System.currentTimeMillis());
        engine.persist("test");
        engine.load("test");
    }
}
