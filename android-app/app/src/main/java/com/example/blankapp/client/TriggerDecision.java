package com.example.blankapp.client;

import android.util.Log;

import org.json.JSONObject;

/**
 * Result of a trigger decision LLM call.
 */
public class TriggerDecision {

    private static final String TAG = "TriggerDecision";

    public final boolean shouldSpeak;
    public final String topicHint;   // short topic phrase, or null
    public final float confidence;   // 0.0 – 1.0

    public TriggerDecision(boolean shouldSpeak, String topicHint, float confidence) {
        this.shouldSpeak = shouldSpeak;
        this.topicHint = topicHint;
        this.confidence = confidence;
    }

    /**
     * Parse the LLM response into a TriggerDecision.
     *
     * Handles:
     * - Clean JSON: {"shouldSpeak": true, "topicHint": "...", "confidence": 0.8}
     * - Markdown-fenced JSON: ```json {...} ```
     * - JSON with leading/trailing noise
     * - JSON null values for topicHint (optString returns "null" for literal null)
     *
     * Falls back to shouldSpeak=false on parse failure (conservative: don't spam).
     */
    public static TriggerDecision fromJson(String raw) {
        if (raw == null || raw.trim().isEmpty()) {
            Log.w(TAG, "fromJson: empty input");
            return noAction();
        }

        String cleaned = extractJsonObject(raw);
        try {
            JSONObject obj = new JSONObject(cleaned);
            boolean shouldSpeak = obj.optBoolean("shouldSpeak", false);

            // optString returns the literal string "null" when the JSON value is null.
            // Check isNull first to get a real Java null.
            String topicHint;
            if (obj.isNull("topicHint")) {
                topicHint = null;
            } else {
                String rawHint = obj.optString("topicHint", null);
                // Also guard against the string "null" leaking through
                topicHint = (rawHint == null || "null".equals(rawHint)) ? null : rawHint;
            }

            float confidence = (float) obj.optDouble("confidence", 0.0);

            Log.d(TAG, "Parsed decision: shouldSpeak=" + shouldSpeak
                    + ", topicHint=" + topicHint + ", confidence=" + confidence);
            return new TriggerDecision(shouldSpeak, topicHint, confidence);
        } catch (Exception e) {
            Log.w(TAG, "Failed to parse decision JSON after cleaning. Raw='"
                    + raw.substring(0, Math.min(200, raw.length())) + "'", e);
            return noAction();
        }
    }

    /**
     * Extract a JSON object from text that may contain markdown fences or noise.
     */
    static String extractJsonObject(String raw) {
        String s = raw.trim();

        // Strip markdown code fences: ```json ... ``` or ``` ... ```
        if (s.startsWith("```")) {
            s = s.replaceAll("```[a-z]*\\s*", "```"); // normalize language tags
            // Remove leading ```
            s = s.replaceFirst("^```\\s*", "");
            // Remove trailing ```
            s = s.replaceFirst("\\s*```\\s*$", "");
            s = s.trim();
        }

        // Try to find JSON object boundaries if there's extra text
        int braceStart = s.indexOf('{');
        int braceEnd = s.lastIndexOf('}');
        if (braceStart >= 0 && braceEnd > braceStart) {
            s = s.substring(braceStart, braceEnd + 1);
        }

        return s;
    }

    public static TriggerDecision noAction() {
        return new TriggerDecision(false, null, 0f);
    }
}
