package com.example.blankapp.client;

import com.example.blankapp.ChatMessage;
import com.example.blankapp.engine.EmotionEngineEvent;
import com.example.blankapp.engine.LifeEngineEvent;
import com.example.blankapp.state.PersonaState;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;

/**
 * Lightweight LLM client for trigger decisions.
 *
 * Sends compact context (last N messages + engine events + persona state) to DeepSeek
 * and asks for a binary decision: should proactively speak now?
 *
 * Uses no thinking/reasoning for low latency (~1-2s vs 10s+).
 */
public class TriggerDecisionClient {

    private final DeepSeekClient llm;

    public TriggerDecisionClient(DeepSeekClient llm) {
        this.llm = llm;
    }

    // ── public API ──────────────────────────────────────────────

    public interface DecisionCallback {
        void onDecision(TriggerDecision decision);
    }

    /**
     * Ask the LLM whether to proactively speak.
     *
     * @param apiKey       DeepSeek API key
     * @param recentMessages last 5-8 messages for context
     * @param lifeEvent     from LifeEngine, may be null
     * @param emotionEvent  from EmotionEngine, may be null
     * @param personaState  current persona state
     * @param callback      receives the decision on main thread
     */
    public void decide(String apiKey,
                       List<ChatMessage> recentMessages,
                       LifeEngineEvent lifeEvent,
                       EmotionEngineEvent emotionEvent,
                       PersonaState personaState,
                       DecisionCallback callback) {

        if (lifeEvent == null && emotionEvent == null) {
            callback.onDecision(TriggerDecision.noAction());
            return;
        }

        String systemPrompt = buildSystemPrompt();
        String contextJson = buildContextJson(recentMessages, lifeEvent, emotionEvent, personaState);

        DeepSeekRequest request = DeepSeekRequest.triggerDecision(systemPrompt, contextJson);

        llm.complete(apiKey, request, new DeepSeekClient.Callback() {
            @Override
            public void onSuccess(String reply) {
                TriggerDecision decision = TriggerDecision.fromJson(reply);
                callback.onDecision(decision);
            }

            @Override
            public void onError(String error) {
                // Fallback: if engines fired, default to speaking with low confidence
                if (lifeEvent != null || emotionEvent != null) {
                    callback.onDecision(new TriggerDecision(true, null, 0.3f));
                } else {
                    callback.onDecision(TriggerDecision.noAction());
                }
            }
        });
    }

    /**
     * Generate the actual proactive message using full LLM reasoning.
     */
    public void generateMessage(String apiKey,
                                String topicHint,
                                List<ChatMessage> recentMessages,
                                PersonaState personaState,
                                DeepSeekClient.Callback callback) {

        String systemPrompt = "你是一个温暖、理性且有主动关心能力的AI伴侣。"
                + "你需要主动发起一段简短的对话。语气自然、真诚，不要像机器人。"
                + "不要用\"我注意到\"、\"根据分析\"这类机械的表达。"
                + "像一个真正关心朋友的人那样说话。"
                + "保持简短（2-4句话）。";

        StringBuilder context = new StringBuilder();
        context.append("最近的对话：\n");
        int start = Math.max(0, recentMessages.size() - 8);
        for (int i = start; i < recentMessages.size(); i++) {
            ChatMessage m = recentMessages.get(i);
            context.append(m.role.equals("user") ? "用户" : "AI").append(": ")
                   .append(m.content).append("\n");
        }

        if (topicHint != null && !topicHint.isEmpty()) {
            context.append("\n建议话题方向：").append(topicHint).append("\n");
        }
        context.append("\n请生成一条主动发起的消息：");

        JSONArray msgs = new JSONArray();
        try {
            JSONObject sys = new JSONObject();
            sys.put("role", "system");
            sys.put("content", systemPrompt);
            msgs.put(sys);
            JSONObject user = new JSONObject();
            user.put("role", "user");
            user.put("content", context.toString());
            msgs.put(user);
        } catch (Exception ignored) {}

        DeepSeekRequest request = new DeepSeekRequest.Builder()
                .messages(msgs)
                .reasoningEffort("medium")
                .maxTokens(200)
                .build();

        llm.complete(apiKey, request, callback);
    }

    // ── prompt builders ─────────────────────────────────────────

    private String buildSystemPrompt() {
        return "You are a proactive companion decision engine. "
                + "Given conversation context, engine events, and persona state, "
                + "decide whether to proactively initiate a check-in with the user.\n\n"
                + "Guidelines:\n"
                + "- ONLY speak if there is a clear reason (emotional signal OR life pattern signal)\n"
                + "- INITIAL_GREETING (fresh contact) and MORNING_CHECK_IN are ALWAYS strong signals — speak warmly\n"
                + "- Emotional distress (SUSTAINED_DISTRESS, NEGATIVE_SHIFT, HIGH_AROUSAL) is a strong signal — speak with care\n"
                + "- ENGAGEMENT_DROP and PROLONGED_IDLE: speak if the context supports it\n"
                + "- If the user is actively chatting, prefer NOT to interrupt\n"
                + "- Respond ONLY with a JSON object (no markdown, no explanation):\n"
                + "  {\"shouldSpeak\": bool, \"topicHint\": \"short Chinese topic\", \"confidence\": 0.0-1.0}\n"
                + "topicHint should be a short Chinese phrase suggesting what to talk about. If shouldSpeak is false, topicHint must be null.";
    }

    private String buildContextJson(List<ChatMessage> recentMessages,
                                    LifeEngineEvent lifeEvent,
                                    EmotionEngineEvent emotionEvent,
                                    PersonaState personaState) {
        JSONObject ctx = new JSONObject();
        try {
            // Recent conversation (last 8 messages max)
            JSONArray convo = new JSONArray();
            int start = Math.max(0, recentMessages.size() - 8);
            for (int i = start; i < recentMessages.size(); i++) {
                ChatMessage m = recentMessages.get(i);
                JSONObject msg = new JSONObject();
                msg.put("role", m.role);
                msg.put("content", m.content.length() > 200
                        ? m.content.substring(0, 200) + "..." : m.content);
                convo.put(msg);
            }
            ctx.put("recentConversation", convo);

            // Life engine event
            if (lifeEvent != null) {
                JSONObject le = new JSONObject();
                le.put("reason", lifeEvent.reason.name());
                le.put("idleMinutes", lifeEvent.idleMinutes);
                le.put("contextHint", lifeEvent.contextHint);
                ctx.put("lifeEvent", le);
            } else {
                ctx.put("lifeEvent", JSONObject.NULL);
            }

            // Emotion engine event
            if (emotionEvent != null) {
                JSONObject ee = new JSONObject();
                ee.put("reason", emotionEvent.reason.name());
                ee.put("urgency", (double) emotionEvent.urgency);
                ee.put("valence", (double) emotionEvent.snapshot.valence);
                ee.put("arousal", (double) emotionEvent.snapshot.arousal);
                ctx.put("emotionEvent", ee);
            } else {
                ctx.put("emotionEvent", JSONObject.NULL);
            }

            // Persona state summary
            JSONObject ps = new JSONObject();
            ps.put("energy", (double) personaState.getEnergy());
            ps.put("mood", (double) personaState.getMood());
            ps.put("motivation", personaState.getMotivation());
            ctx.put("personaState", ps);
        } catch (Exception ignored) {}
        return ctx.toString();
    }
}
