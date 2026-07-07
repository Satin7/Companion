package com.example.blankapp.engine;

/**
 * Event emitted by EmotionEngine when an emotional trigger condition is met.
 */
public class EmotionEngineEvent {

    public enum Reason {
        /** Emotional valence has dropped significantly below the user's baseline. */
        NEGATIVE_SHIFT,
        /** Emotional intensity (arousal) is unusually high. */
        HIGH_AROUSAL,
        /** Sustained negative deviation across multiple turns. */
        SUSTAINED_DISTRESS
    }

    public final Reason reason;
    public final EmotionalProfile snapshot;
    public final float urgency;      // 0.0 – 1.0, how urgently a check-in is needed

    public EmotionEngineEvent(Reason reason, EmotionalProfile snapshot, float urgency) {
        this.reason = reason;
        this.snapshot = snapshot;
        this.urgency = urgency;
    }
}
