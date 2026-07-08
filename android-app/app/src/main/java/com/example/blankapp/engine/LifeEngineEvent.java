package com.example.blankapp.engine;

/**
 * Event emitted by LifeEngine when a temporal trigger condition is met.
 */
public class LifeEngineEvent {

    public enum Reason {
        /** User has been idle longer than their typical active window allows. */
        PROLONGED_IDLE,
        /** Today's interaction count is significantly below historical average. */
        ENGAGEMENT_DROP,
        /** It's morning / start of typical active hours and user hasn't chatted yet. */
        MORNING_CHECK_IN,
        /** User just returned after a long gap — welcome-back moment. */
        RETURN_AFTER_GAP,
        /** Fresh contact with zero interaction history — prime time for first greeting. */
        INITIAL_GREETING
    }

    public final Reason reason;
    public final float confidence;   // 0.0 – 1.0
    public final String contextHint; // human-readable hint for LLM prompt
    public final long idleMinutes;

    public LifeEngineEvent(Reason reason, float confidence, String contextHint, long idleMinutes) {
        this.reason = reason;
        this.confidence = confidence;
        this.contextHint = contextHint;
        this.idleMinutes = idleMinutes;
    }
}
