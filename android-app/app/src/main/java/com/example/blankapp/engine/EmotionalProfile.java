package com.example.blankapp.engine;

import org.json.JSONObject;

/**
 * Snapshot of emotional dimensions extracted from recent conversation.
 */
public class EmotionalProfile {

    /** -1.0 (very negative) to +1.0 (very positive) */
    public final float valence;

    /** Intensity / activation level, 0.0 (calm) to 1.0 (highly activated) */
    public final float arousal;

    /** Sense of control / agency, 0.0 (powerless) to 1.0 (in control) */
    public final float dominance;

    /** Extracted topic keywords, e.g. ["压力", "睡眠", "工作"] */
    public final String[] keyThemes;

    public final long timestamp;

    public EmotionalProfile(float valence, float arousal, float dominance,
                            String[] keyThemes, long timestamp) {
        this.valence = clamp(valence, -1f, 1f);
        this.arousal = clamp(arousal, 0f, 1f);
        this.dominance = clamp(dominance, 0f, 1f);
        this.keyThemes = keyThemes != null ? keyThemes : new String[0];
        this.timestamp = timestamp;
    }

    public boolean isNegative() {
        return valence < -0.2f;
    }

    public boolean isHighlyAroused() {
        return arousal > 0.7f;
    }

    // ── serialisation ───────────────────────────────────────────

    public JSONObject toJson() {
        JSONObject obj = new JSONObject();
        try {
            obj.put("valence", (double) valence);
            obj.put("arousal", (double) arousal);
            obj.put("dominance", (double) dominance);
            obj.put("timestamp", timestamp);
        } catch (Exception ignored) {}
        return obj;
    }

    public static EmotionalProfile fromJson(JSONObject obj) {
        return new EmotionalProfile(
                (float) obj.optDouble("valence", 0.0),
                (float) obj.optDouble("arousal", 0.5),
                (float) obj.optDouble("dominance", 0.5),
                new String[0],
                obj.optLong("timestamp", System.currentTimeMillis())
        );
    }

    public static EmotionalProfile neutral() {
        return new EmotionalProfile(0f, 0.5f, 0.5f, new String[0], System.currentTimeMillis());
    }

    private static float clamp(float v, float lo, float hi) {
        return Math.max(lo, Math.min(hi, v));
    }
}
