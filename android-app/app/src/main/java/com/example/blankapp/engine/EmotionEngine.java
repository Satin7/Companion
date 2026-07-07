package com.example.blankapp.engine;

import android.content.Context;
import android.content.SharedPreferences;

import com.example.blankapp.ChatMessage;
import com.example.blankapp.client.DeepSeekClient;
import com.example.blankapp.client.DeepSeekRequest;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * Tracks emotional signals from conversation text and fires events
 * when emotional state crosses thresholds.
 *
 * State machine: NEUTRAL → HEIGHTENED → DISTRESSED
 *
 * Uses lightweight LLM calls for sentiment classification (not generation).
 * Results are cached per message-set to avoid redundant API calls.
 *
 * Persisted per contactId.
 */
public class EmotionEngine {

    private static final String PREFS_NAME = "emotion_engine_state";
    private static final int WINDOW_SIZE = 6;

    enum State { NEUTRAL, HEIGHTENED, DISTRESSED }

    private State state = State.NEUTRAL;
    private EmotionalProfile baseline = EmotionalProfile.neutral();
    private EmotionalProfile currentProfile = EmotionalProfile.neutral();
    private int derailmentCount; // consecutive turns with significant negative deviation
    private float negativeKeywordsWeight;
    private long lastAnalysisTimestamp;
    private String lastMessageSetHash;

    private final SharedPreferences prefs;
    private DeepSeekClient llmClient; // injected, not owned

    public EmotionEngine(Context context) {
        this.prefs = context.getApplicationContext()
                .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    /** Inject the LLM client after construction. */
    public void setLlmClient(DeepSeekClient client) {
        this.llmClient = client;
    }

    // ── input ───────────────────────────────────────────────────

    /**
     * Feed recent messages for emotional analysis.
     * Analysis is performed asynchronously via LLM; results update internal state.
     *
     * @param apiKey  DeepSeek API key
     * @param messages  recent messages (last N)
     * @param onComplete  called on main thread when analysis finishes
     */
    public void analyzeMessages(String apiKey, List<ChatMessage> messages, Runnable onComplete) {
        if (llmClient == null || messages.isEmpty()) {
            if (onComplete != null) onComplete.run();
            return;
        }

        // Skip if already analysed this exact set
        String hash = computeHash(messages);
        if (hash.equals(lastMessageSetHash)) {
            if (onComplete != null) onComplete.run();
            return;
        }

        DeepSeekRequest req = buildSentimentRequest(messages);
        llmClient.complete(apiKey, req, new DeepSeekClient.Callback() {
            @Override
            public void onSuccess(String reply) {
                EmotionalProfile profile = parseSentimentResponse(reply);
                if (profile != null) {
                    updateState(profile);
                    lastMessageSetHash = hash;
                    lastAnalysisTimestamp = System.currentTimeMillis();
                }
                if (onComplete != null) onComplete.run();
            }

            @Override
            public void onError(String error) {
                // Degrade gracefully: use keyword-based fallback
                EmotionalProfile fallback = keywordFallback(messages);
                updateState(fallback);
                lastMessageSetHash = hash;
                lastAnalysisTimestamp = System.currentTimeMillis();
                if (onComplete != null) onComplete.run();
            }
        });
    }

    // ── output ──────────────────────────────────────────────────

    /** Returns an event if emotional state warrants proactive contact, otherwise null. */
    public EmotionEngineEvent checkForEmotionalSignal() {
        float urgency = 0f;
        EmotionEngineEvent.Reason reason = null;

        if (state == State.DISTRESSED) {
            urgency = Math.min(1f, 0.6f + derailmentCount * 0.1f);
            reason = EmotionEngineEvent.Reason.SUSTAINED_DISTRESS;
        } else if (state == State.HEIGHTENED) {
            urgency = 0.4f + negativeKeywordsWeight * 0.3f;
            if (currentProfile.isHighlyAroused()) {
                reason = EmotionEngineEvent.Reason.HIGH_AROUSAL;
            } else {
                reason = EmotionEngineEvent.Reason.NEGATIVE_SHIFT;
            }
        }

        if (reason != null && urgency > 0.35f) {
            // Reset derailment after firing (but state stays until recovery)
            derailmentCount = Math.max(0, derailmentCount - 1);
            return new EmotionEngineEvent(reason, currentProfile, urgency);
        }

        return null;
    }

    // ── state machine ───────────────────────────────────────────

    private void updateState(EmotionalProfile profile) {
        currentProfile = profile;

        // Update baseline (slow-moving average)
        baseline = new EmotionalProfile(
                baseline.valence * 0.9f + profile.valence * 0.1f,
                baseline.arousal * 0.9f + profile.arousal * 0.1f,
                baseline.dominance * 0.9f + profile.dominance * 0.1f,
                baseline.keyThemes,
                System.currentTimeMillis()
        );

        float valenceShift = profile.valence - baseline.valence;

        switch (state) {
            case NEUTRAL:
                if (valenceShift < -0.3f || profile.isHighlyAroused()) {
                    state = State.HEIGHTENED;
                    derailmentCount = 1;
                }
                break;
            case HEIGHTENED:
                if (valenceShift < -0.15f) {
                    derailmentCount++;
                    if (derailmentCount >= 3) {
                        state = State.DISTRESSED;
                    }
                } else if (valenceShift > -0.05f) {
                    // returning to baseline
                    derailmentCount = Math.max(0, derailmentCount - 1);
                    if (derailmentCount == 0) {
                        state = State.NEUTRAL;
                    }
                }
                break;
            case DISTRESSED:
                if (valenceShift > -0.1f) {
                    derailmentCount = Math.max(0, derailmentCount - 1);
                    if (derailmentCount <= 1) {
                        state = State.HEIGHTENED; // step down, not straight to neutral
                    }
                }
                break;
        }

        // Keyword weight for urgency gating
        negativeKeywordsWeight = estimateNegativeWeight(profile);
    }

    // ── sentiment request ───────────────────────────────────────

    private DeepSeekRequest buildSentimentRequest(List<ChatMessage> messages) {
        StringBuilder convo = new StringBuilder();
        for (ChatMessage m : messages) {
            convo.append(m.role).append(": ").append(m.content).append("\n");
        }

        String sysPrompt = "You are an emotion analysis engine. Given the conversation below, "
                + "output ONLY a JSON object with these fields:\n"
                + "- valence: float from -1.0 (very negative) to 1.0 (very positive)\n"
                + "- arousal: float from 0.0 (calm) to 1.0 (highly activated)\n"
                + "- dominance: float from 0.0 (powerless) to 1.0 (in control)\n"
                + "- keyThemes: array of 1-3 short topic keywords in Chinese\n"
                + "No explanation, no markdown, only the JSON object.";

        return new DeepSeekRequest.Builder()
                .messages(makeMessages(sysPrompt, convo.toString()))
                .noThinking()
                .maxTokens(128)
                .build();
    }

    private EmotionalProfile parseSentimentResponse(String raw) {
        try {
            String trimmed = raw.trim();
            // Strip markdown code fences if present
            if (trimmed.startsWith("```")) {
                trimmed = trimmed.replaceAll("```[a-z]*\\s*", "").trim();
            }
            JSONObject obj = new JSONObject(trimmed);
            JSONArray themesArr = obj.optJSONArray("keyThemes");
            String[] themes;
            if (themesArr != null) {
                themes = new String[themesArr.length()];
                for (int i = 0; i < themesArr.length(); i++) {
                    themes[i] = themesArr.getString(i);
                }
            } else {
                themes = new String[0];
            }
            return new EmotionalProfile(
                    (float) obj.optDouble("valence", 0.0),
                    (float) obj.optDouble("arousal", 0.5),
                    (float) obj.optDouble("dominance", 0.5),
                    themes,
                    System.currentTimeMillis()
            );
        } catch (Exception e) {
            return null;
        }
    }

    // ── keyword fallback (no LLM) ───────────────────────────────

    private EmotionalProfile keywordFallback(List<ChatMessage> messages) {
        float negativeScore = 0f;
        int totalWords = 0;
        List<String> themes = new ArrayList<>();

        String[] negativeWords = {"担心", "累", "难", "烦", "焦虑", "压力", "不开心",
                "难过", "生气", "崩溃", "失眠", "头痛", "害怕", "无聊", "孤独"};
        String[] highArousalWords = {"太", "非常", "很", "特别", "急", "快", "一直", "总是"};

        for (ChatMessage m : messages) {
            if (!"user".equals(m.role)) continue;
            String text = m.content;
            for (String w : negativeWords) {
                if (text.contains(w)) {
                    negativeScore += 0.15f;
                    if (!themes.contains(w)) themes.add(w);
                }
            }
            for (String w : highArousalWords) {
                if (text.contains(w)) negativeScore += 0.05f;
            }
            totalWords += text.length();
        }

        float valence = Math.max(-1f, -negativeScore);
        float arousal = Math.min(1f, negativeScore * 1.5f);

        return new EmotionalProfile(
                valence,
                arousal,
                0.5f,
                themes.toArray(new String[0]),
                System.currentTimeMillis()
        );
    }

    private float estimateNegativeWeight(EmotionalProfile profile) {
        float w = 0f;
        if (profile.valence < -0.3f) w += 0.3f;
        if (profile.valence < -0.6f) w += 0.3f;
        if (profile.arousal > 0.7f) w += 0.2f;
        if (profile.dominance < 0.3f) w += 0.2f;
        return Math.min(1f, w);
    }

    // ── persistence ─────────────────────────────────────────────

    public void persist(String contactId) {
        JSONObject obj = new JSONObject();
        try {
            obj.put("state", state.name());
            obj.put("baseline", baseline.toJson());
            obj.put("derailmentCount", derailmentCount);
            obj.put("negativeKeywordsWeight", (double) negativeKeywordsWeight);
            obj.put("lastAnalysisTimestamp", lastAnalysisTimestamp);
        } catch (Exception ignored) {}
        prefs.edit().putString(contactId, obj.toString()).apply();
    }

    public void load(String contactId) {
        String raw = prefs.getString(contactId, null);
        if (raw == null || raw.isEmpty()) return;
        try {
            JSONObject obj = new JSONObject(raw);
            state = State.valueOf(obj.optString("state", "NEUTRAL"));
            JSONObject baseJson = obj.optJSONObject("baseline");
            if (baseJson != null) {
                baseline = EmotionalProfile.fromJson(baseJson);
            }
            derailmentCount = obj.optInt("derailmentCount", 0);
            negativeKeywordsWeight = (float) obj.optDouble("negativeKeywordsWeight", 0.0);
            lastAnalysisTimestamp = obj.optLong("lastAnalysisTimestamp", 0);
        } catch (Exception ignored) {}
    }

    // ── util ────────────────────────────────────────────────────

    private String computeHash(List<ChatMessage> messages) {
        StringBuilder sb = new StringBuilder();
        int start = Math.max(0, messages.size() - WINDOW_SIZE);
        for (int i = start; i < messages.size(); i++) {
            ChatMessage m = messages.get(i);
            sb.append(m.role).append(":").append(m.content).append("|");
        }
        return String.valueOf(sb.toString().hashCode());
    }

    private static org.json.JSONArray makeMessages(String systemPrompt, String userContent) {
        org.json.JSONArray arr = new org.json.JSONArray();
        try {
            JSONObject sys = new JSONObject();
            sys.put("role", "system");
            sys.put("content", systemPrompt);
            arr.put(sys);
            JSONObject user = new JSONObject();
            user.put("role", "user");
            user.put("content", userContent);
            arr.put(user);
        } catch (Exception ignored) {}
        return arr;
    }
}
