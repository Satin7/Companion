package com.example.blankapp.engine;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.HashSet;
import java.util.Set;

/**
 * Tracks temporal patterns of user interaction and fires events when
 * user behaviour signals a meaningful window for proactive contact.
 *
 * State machine: IDLE → OBSERVING → READY → (back to OBSERVING)
 *
 * Persisted per contactId so state survives activity restarts.
 */
public class LifeEngine {

    private static final String TAG = "LifeEngine";
    private static final String PREFS_NAME = "life_engine_state";

    // ── configurable thresholds ─────────────────────────────────

    private static final float ENGAGEMENT_DROP_RATIO = 0.3f; // 30% of average
    private static final int MIN_INTERACTIONS_FOR_ENGAGEMENT_DROP = 5;
    private static final long MIN_REPEAT_SIGNAL_INTERVAL_MS = 30 * 60 * 1000L; // 30 min cooldown

    // ── state ───────────────────────────────────────────────────

    enum State { IDLE, OBSERVING, READY }

    private State state = State.IDLE;
    private long lastInteractionTimestamp;
    private int interactionCountToday;
    private final Set<Integer> activeHours = new HashSet<>(); // hours of day (0-23) user is active
    private int historicalDailyAvg = 10; // rolling estimate, seeded at 10
    private long idleThresholdMs = 2 * 60 * 60 * 1000L; // default 2 hours
    private long lastSignalTimestamp = 0; // prevent re-firing the same signal
    private LifeEngineEvent.Reason lastSignalReason = null;
    private boolean hasAnyInteraction = false; // true once user sends at least one message

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

    // ── input signals ───────────────────────────────────────────

    /** Call when the user sends a message. */
    public void onUserMessage(long timestamp) {
        lastInteractionTimestamp = timestamp;
        interactionCountToday++;
        hasAnyInteraction = true;

        int hour = hourOfDay(timestamp);
        activeHours.add(hour);

        // Update rolling average
        historicalDailyAvg = (historicalDailyAvg * 4 + interactionCountToday) / 5;

        if (state == State.IDLE) {
            state = State.OBSERVING;
        } else if (state == State.READY) {
            state = State.OBSERVING; // user re-engaged, reset
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
        if (state != State.READY) return null;

        long idleMinutes = (now - lastInteractionTimestamp) / 60_000L;

        LifeEngineEvent.Reason reason;
        String hint;

        // Determine the strongest signal
        boolean freshContact = interactionCountToday == 0
                && !hasAnyInteraction
                && activeHours.isEmpty();

        if (freshContact) {
            reason = LifeEngineEvent.Reason.INITIAL_GREETING;
            hint = "用户还未进行过任何对话，是发起首次主动问候的好时机";
        } else if (interactionCountToday == 0 && hourOfDay(now) >= 10) {
            reason = LifeEngineEvent.Reason.MORNING_CHECK_IN;
            hint = "用户今天还没有开始聊天，可以问候早安";
        } else if (interactionCountToday >= MIN_INTERACTIONS_FOR_ENGAGEMENT_DROP
                && historicalDailyAvg > 0
                && interactionCountToday < historicalDailyAvg * ENGAGEMENT_DROP_RATIO) {
            reason = LifeEngineEvent.Reason.ENGAGEMENT_DROP;
            hint = "用户今天的互动明显少于平常，可能心情不好或很忙";
        } else {
            reason = LifeEngineEvent.Reason.PROLONGED_IDLE;
            hint = "用户已经 " + idleMinutes + " 分钟没有互动了，通常在此时段活跃";
        }

        // ── cooldown: don't re-fire the same reason too quickly ──
        if (reason == lastSignalReason
                && (now - lastSignalTimestamp) < MIN_REPEAT_SIGNAL_INTERVAL_MS) {
            Log.d(TAG, "checkForLifeSignal: cooldown active for reason=" + reason
                    + ", remaining=" + (MIN_REPEAT_SIGNAL_INTERVAL_MS - (now - lastSignalTimestamp)) / 60_000L + "min");
            state = State.OBSERVING; // stay quiet, try again later
            return null;
        }

        float confidence = Math.min(0.95f, idleMinutes / 480f); // scales to 0.95 over 8h

        // Transition back after firing
        state = State.OBSERVING;
        lastSignalTimestamp = now;
        lastSignalReason = reason;

        Log.i(TAG, "checkForLifeSignal: FIRING reason=" + reason
                + ", confidence=" + confidence + ", idleMinutes=" + idleMinutes);
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
