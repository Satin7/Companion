package com.example.blankapp.engine;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import org.junit.Before;
import org.junit.Test;

/**
 * Pure JUnit tests for LifeEngine state machine logic.
 */
public class LifeEngineTest {

    private LifeEngine engine;

    @Before
    public void setUp() {
        engine = new LifeEngine(null);
    }

    @Test
    public void initialStateIsIdle() {
        assertNull(engine.checkForLifeSignal(System.currentTimeMillis()));
    }

    @Test
    public void onUserMessage_transitionsToObserving() {
        engine.onUserMessage(System.currentTimeMillis());
        assertNull(engine.checkForLifeSignal(System.currentTimeMillis()));
    }

    @Test
    public void testMode_withShortThreshold_triggersViaEngagementDrop() {
        engine.setIdleThresholdMs(60_000L);
        long now = System.currentTimeMillis();
        // Simulate a user message 90s ago
        engine.onUserMessage(now - 90_000L);
        engine.onTimerTick(now);

        LifeEngineEvent event = engine.checkForLifeSignal(now);
        // After one message, histAvg ~8, engagement_drop: 1 < 2.4 → true
        assertNotNull("Should fire via ENGAGEMENT_DROP or similar", event);
    }

    @Test
    public void afterUserMessage_firingResets() {
        long now = System.currentTimeMillis();
        engine.onUserMessage(now - 90_000L);
        engine.setIdleThresholdMs(60_000L);
        engine.onTimerTick(now);

        engine.checkForLifeSignal(now); // fires, resets to OBSERVING
        LifeEngineEvent second = engine.checkForLifeSignal(now + 100L);
        assertNull("Should not fire twice without re-trigger", second);
    }

    @Test
    public void userMessageResetsReadyState() {
        long now = System.currentTimeMillis();
        engine.onUserMessage(now - 90_000L);
        engine.setIdleThresholdMs(60_000L);
        engine.onTimerTick(now);

        // User sends another message
        engine.onUserMessage(now + 200L);
        assertNull(engine.checkForLifeSignal(now + 300L));
    }

    @Test
    public void freshContactWithIdle_triggers() {
        long now = System.currentTimeMillis();
        engine.setIdleThresholdMs(100L);
        engine.onTimerTick(now + 200L);

        LifeEngineEvent event = engine.checkForLifeSignal(now + 200L);
        assertNotNull("Should trigger for fresh contact", event);
    }

    @Test
    public void persistWithNullContext_doesNotCrash() {
        engine.onUserMessage(System.currentTimeMillis());
        engine.persist("test");
    }

    @Test
    public void loadWithNullContext_doesNotCrash() {
        engine.load("test");
    }
}
