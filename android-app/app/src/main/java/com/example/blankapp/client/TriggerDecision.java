package com.example.blankapp.client;

import org.json.JSONObject;

/**
 * Result of a trigger decision LLM call.
 */
public class TriggerDecision {

    public final boolean shouldSpeak;
    public final String topicHint;   // short topic phrase, or null
    public final float confidence;   // 0.0 – 1.0

    public TriggerDecision(boolean shouldSpeak, String topicHint, float confidence) {
        this.shouldSpeak = shouldSpeak;
        this.topicHint = topicHint;
        this.confidence = confidence;
    }

    public static TriggerDecision fromJson(String raw) {
        try {
            JSONObject obj = new JSONObject(raw.trim());
            return new TriggerDecision(
                    obj.optBoolean("shouldSpeak", false),
                    obj.optString("topicHint", null),
                    (float) obj.optDouble("confidence", 0.0)
            );
        } catch (Exception e) {
            return new TriggerDecision(false, null, 0f);
        }
    }

    public static TriggerDecision noAction() {
        return new TriggerDecision(false, null, 0f);
    }
}
