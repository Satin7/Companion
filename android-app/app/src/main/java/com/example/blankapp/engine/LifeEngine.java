package com.example.blankapp.engine;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.HashSet;
import java.util.Set;

/**
 * LifeEngine — "Companion 的周围世界"
 *
 * Tracks what's happening around the Companion: time passing, user messages,
 * and the interaction rhythm (PRESENT/ABSENT).
 *
 * State machine: IDLE → OBSERVING → READY → (back to OBSERVING)
 *
 * Persisted per contactId so state survives activity restarts.
 */
public class LifeEngine {

    private static final String TAG = "LifeEngine";
    private static final String PREFS_NAME = "life_engine_state";

    // ── configurable thresholds ─────────────────────────────────

    private static final float ENGAGEMENT_DROP_RATIO = 0.3f;
    private static final int MIN_INTERACTIONS_FOR_ENGAGEMENT_DROP = 5;
    private static final long MIN_REPEAT_SIGNAL_INTERVAL_MS = 30 * 60 * 1000L;

    // ── interaction mode ────────────────────────────────────────

    public enum InteractionMode { PRESENT, ABSENT }

    // ── state ───────────────────────────────────────────────────

    enum State { IDLE, OBSERVING, READY }

    private State state = State.IDLE;
    private InteractionMode interactionMode = InteractionMode.PRESENT;
    private long lastInteractionTimestamp;
    private long lastProactiveSentTimestamp;
    private int consecutiveNoReply;
    private int interactionCountToday;
    private final Set<Integer> activeHours = new HashSet<>();
    private int historicalDailyAvg = 10;
    private long idleThresholdMs = 2 * 60 * 60 * 1000L;
    private long lastSignalTimestamp = 0;
    private LifeEngineEvent.Reason lastSignalReason = null;
    private boolean hasAnyInteraction = false;
    private float lastUserMsgNeedCare;
    private float lastUserMsgIntensity;

    private final SharedPreferences prefs;

    public LifeEngine(Context context) {
        this.prefs = context != null
                ? context.getApplicationContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                : null;
    }

    /** Override the idle threshold. Use e.g. 60_000 for 1-minute test mode. */
    public void setIdleThresholdMs(long ms) {
        this.idleThresholdMs = ms;
    }

    // ── accessors ───────────────────────────────────────────────

    public InteractionMode getInteractionMode() { return interactionMode; }
    public int getConsecutiveNoReply() { return consecutiveNoReply; }
    public long getLastInteractionTimestamp() { return lastInteractionTimestamp; }
    public float getLastUserMsgNeedCare() { return lastUserMsgNeedCare; }
    public float getLastUserMsgIntensity() { return lastUserMsgIntensity; }

    // ── input signals ───────────────────────────────────────────

    /** Call when the user sends a message. Analyzes content for signals. */
    public void onUserMessage(long timestamp) {
        onUserMessage(timestamp, null);
    }

    public void onUserMessage(long timestamp, String msgText) {
        lastInteractionTimestamp = timestamp;
        interactionCountToday++;
        hasAnyInteraction = true;
        consecutiveNoReply = 0; // user replied → reset

        int hour = hourOfDay(timestamp);
        activeHours.add(hour);

        historicalDailyAvg = (historicalDailyAvg * 4 + interactionCountToday) / 5;

        // Analyze message content (keyword-based, no LLM needed)
        if (msgText != null && !msgText.isEmpty()) {
            analyzeUserMessage(msgText);
        }

        // Switch to PRESENT if user is messaging
        if (interactionMode == InteractionMode.ABSENT) {
            Log.i(TAG, "InteractionState → PRESENT (user sent message)");
            interactionMode = InteractionMode.PRESENT;
        }

        if (state == State.IDLE) {
            state = State.OBSERVING;
        } else if (state == State.READY) {
            state = State.OBSERVING;
        }
    }

    /** Keyword-based user message analysis. Simple, fast, no LLM cost. */
    private void analyzeUserMessage(String text) {
        String[] needCareWords = {"累", "难", "烦", "焦虑", "压力", "不开心", "难过", "崩溃", "失眠", "害怕", "孤独", "担心", "不舒服", "生病"};
        String[] intensityWords = {"太", "非常", "很", "特别", "急", "一直", "总是", "真的", "超级"};

        int needCare = 0, intensity = 0;
        for (String w : needCareWords) { if (text.contains(w)) needCare++; }
        for (String w : intensityWords) { if (text.contains(w)) intensity++; }

        lastUserMsgNeedCare = Math.min(1f, needCare * 0.4f);
        lastUserMsgIntensity = Math.min(1f, intensity * 0.3f);
    }

    /** Call after Companion sends a proactive message (not a normal reply). */
    public void onProactiveSent(long timestamp) {
        lastProactiveSentTimestamp = timestamp;
        consecutiveNoReply++;
    }

    /** Evaluate interaction mode transitions. */
    public void evaluateInteractionMode(long now) {
        long idleMs = now - lastInteractionTimestamp;
        long absentThreshold = Math.min(idleThresholdMs, 5 * 60 * 1000L);
        if (interactionMode == InteractionMode.PRESENT && idleMs > absentThreshold) {
            interactionMode = InteractionMode.ABSENT;
            Log.i(TAG, "InteractionState → ABSENT (silent " + (idleMs / 60000) + "min)");
        }
    }

    /** Call on each scheduler tick. Evaluates idle time and transitions. */
    public void onTimerTick(long now) {
        long idleMs = now - lastInteractionTimestamp;

        if (state == State.OBSERVING || state == State.IDLE) {
            boolean idleTooLong = idleMs > idleThresholdMs;
            // If no active hours recorded yet (fresh contact), treat all hours as active
            boolean inActiveWindow = activeHours.isEmpty()
                    || activeHours.contains(hourOfDay(now));
            // Engagement drop: only fire if user has enough history to make it meaningful
            boolean engagementDropped = interactionCountToday >= MIN_INTERACTIONS_FOR_ENGAGEMENT_DROP
                    && interactionCountToday < historicalDailyAvg * ENGAGEMENT_DROP_RATIO;
            boolean morningNoChat = hourOfDay(now) >= 10 && interactionCountToday == 0;
            // Fresh contact with no interaction history at all — prime time for greeting
            boolean freshContact = interactionCountToday == 0
                    && !hasAnyInteraction
                    && activeHours.isEmpty();

            if (morningNoChat) {
                Log.i(TAG, "onTimerTick: MORNING_CHECK_IN triggered, state=READY");
                state = State.READY;
            } else if (freshContact) {
                Log.i(TAG, "onTimerTick: FRESH_CONTACT triggered, state=READY");
                state = State.READY;
            } else if (engagementDropped) {
                Log.i(TAG, "onTimerTick: ENGAGEMENT_DROP triggered (today="
                        + interactionCountToday + " vs avg=" + historicalDailyAvg + "), state=READY");
                state = State.READY;
            } else if (idleTooLong && inActiveWindow) {
                Log.i(TAG, "onTimerTick: PROLONGED_IDLE triggered (idleMs=" + idleMs
                        + " > threshold=" + idleThresholdMs + "), state=READY");
                state = State.READY;
            }
        }
    }

    // ── output ──────────────────────────────────────────────────

    /** Returns an event if the engine is READY, otherwise null. */
    public LifeEngineEvent checkForLifeSignal(long now) {
        evaluateInteractionMode(now);

        if (state != State.READY) return null;

        long idleMinutes = (now - lastInteractionTimestamp) / 60_000L;
        LifeEngineEvent.Reason reason;
        String hint;

        boolean freshContact = interactionCountToday == 0 && !hasAnyInteraction && activeHours.isEmpty();

        if (freshContact) {
            reason = LifeEngineEvent.Reason.INITIAL_GREETING;
            hint = "全新联系人，发起首次问候";
        } else if (interactionCountToday == 0 && hourOfDay(now) >= 10) {
            reason = LifeEngineEvent.Reason.MORNING_CHECK_IN;
            hint = "用户今天还没有聊天";
        } else {
            reason = LifeEngineEvent.Reason.PROLONGED_IDLE;
            hint = "用户空闲 " + idleMinutes + " 分钟";
        }

        if (reason == lastSignalReason
                && (now - lastSignalTimestamp) < MIN_REPEAT_SIGNAL_INTERVAL_MS) {
            Log.d(TAG, "checkForLifeSignal: cooldown active for " + reason);
            state = State.OBSERVING;
            return null;
        }

        float confidence = Math.min(0.95f, idleMinutes / 480f);
        state = State.OBSERVING;
        lastSignalTimestamp = now;
        lastSignalReason = reason;

        Log.i(TAG, "checkForLifeSignal: " + reason + " mode=" + interactionMode
                + " idleMin=" + idleMinutes + " confidence=" + confidence);
        return new LifeEngineEvent(reason, confidence, hint, idleMinutes);
    }

    // ── persistence ─────────────────────────────────────────────

    public void persist(String contactId) {
        JSONObject obj = new JSONObject();
        try {
            obj.put("state", state.name());
            obj.put("lastInteraction", lastInteractionTimestamp);
            obj.put("interactionCountToday", interactionCountToday);
            obj.put("historicalDailyAvg", historicalDailyAvg);
            obj.put("lastSignalTimestamp", lastSignalTimestamp);
            obj.put("lastSignalReason", lastSignalReason != null ? lastSignalReason.name() : null);
            obj.put("hasAnyInteraction", hasAnyInteraction);
            JSONArray hours = new JSONArray();
            for (int h : activeHours) hours.put(h);
            obj.put("activeHours", hours);
        } catch (Exception ignored) {}
        if (prefs == null) return;
        prefs.edit().putString(contactId, obj.toString()).apply();
    }

    public void load(String contactId) {
        if (prefs == null) return;
        String raw = prefs.getString(contactId, null);
        if (raw == null || raw.isEmpty()) {
            lastInteractionTimestamp = System.currentTimeMillis();
            return;
        }
        try {
            JSONObject obj = new JSONObject(raw);
            state = State.valueOf(obj.optString("state", "IDLE"));
            lastInteractionTimestamp = obj.optLong("lastInteraction", System.currentTimeMillis());
            interactionCountToday = obj.optInt("interactionCountToday", 0);
            historicalDailyAvg = obj.optInt("historicalDailyAvg", 10);
            lastSignalTimestamp = obj.optLong("lastSignalTimestamp", 0);
            String reasonStr = obj.optString("lastSignalReason", null);
            lastSignalReason = (reasonStr != null && !reasonStr.equals("null"))
                    ? LifeEngineEvent.Reason.valueOf(reasonStr) : null;
            hasAnyInteraction = obj.optBoolean("hasAnyInteraction", false);
            activeHours.clear();
            JSONArray hours = obj.optJSONArray("activeHours");
            if (hours != null) {
                for (int i = 0; i < hours.length(); i++) {
                    activeHours.add(hours.getInt(i));
                }
            }
        } catch (Exception e) {
            lastInteractionTimestamp = System.currentTimeMillis();
            state = State.IDLE;
        }
    }

    // ── util ────────────────────────────────────────────────────

    private static int hourOfDay(long timestamp) {
        java.util.Calendar cal = java.util.Calendar.getInstance();
        cal.setTimeInMillis(timestamp);
        return cal.get(java.util.Calendar.HOUR_OF_DAY);
    }
}
