package com.example.blankapp.client;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Immutable value object for a DeepSeek chat completion request.
 */
public class DeepSeekRequest {

    public final String model;
    public final JSONArray messages;
    public final String reasoningEffort;   // "minimal", "low", "medium", "high", or null to omit thinking
    public final int maxTokens;
    public final boolean stream;

    private DeepSeekRequest(Builder builder) {
        this.model = builder.model;
        this.messages = builder.messages;
        this.reasoningEffort = builder.reasoningEffort;
        this.maxTokens = builder.maxTokens;
        this.stream = builder.stream;
    }

    public JSONObject toJson() {
        JSONObject body = new JSONObject();
        try {
            body.put("model", model);
            body.put("messages", messages);
            body.put("stream", stream);
            if (maxTokens > 0) {
                body.put("max_tokens", maxTokens);
            }
            if (reasoningEffort != null && !reasoningEffort.isEmpty()) {
                JSONObject thinking = new JSONObject();
                thinking.put("type", "enabled");
                body.put("thinking", thinking);
                body.put("reasoning_effort", reasoningEffort);
            }
        } catch (Exception ignored) {
        }
        return body;
    }

    public static class Builder {
        private String model = "deepseek-v4-pro";
        private JSONArray messages = new JSONArray();
        private String reasoningEffort = "high";
        private int maxTokens = 0;
        private boolean stream = false;

        public Builder model(String model) { this.model = model; return this; }
        public Builder messages(JSONArray messages) { this.messages = messages; return this; }
        public Builder reasoningEffort(String effort) { this.reasoningEffort = effort; return this; }
        public Builder noThinking() { this.reasoningEffort = null; return this; }
        public Builder maxTokens(int tokens) { this.maxTokens = tokens; return this; }
        public Builder stream(boolean stream) { this.stream = stream; return this; }
        public DeepSeekRequest build() { return new DeepSeekRequest(this); }
    }

    // ── convenience factories ───────────────────────────────────

    public static DeepSeekRequest replyGeneration(String systemPrompt, String userMessage) {
        JSONArray msgs = new JSONArray();
        msgs.put(makeMessage("system", systemPrompt));
        msgs.put(makeMessage("user", userMessage));
        return new Builder()
                .messages(msgs)
                .reasoningEffort("high")
                .build();
    }

    public static DeepSeekRequest triggerDecision(String systemPrompt, String contextJson) {
        JSONArray msgs = new JSONArray();
        msgs.put(makeMessage("system", systemPrompt));
        msgs.put(makeMessage("user", contextJson));
        return new Builder()
                .messages(msgs)
                .noThinking()
                .maxTokens(256)
                .build();
    }

    private static JSONObject makeMessage(String role, String content) {
        JSONObject msg = new JSONObject();
        try {
            msg.put("role", role);
            msg.put("content", content);
        } catch (Exception ignored) {
        }
        return msg;
    }
}
