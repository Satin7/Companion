package com.example.blankapp.engine;

import android.content.Context;
import android.content.SharedPreferences;

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

    private static final String PREFS_NAME = "life_engine_state";

    // ── configurable thresholds ─────────────────────────────────

    private static final float ENGAGEMENT_DROP_RATIO = 0.3f; // 30% of average

    // ── state ───────────────────────────────────────────────────

    enum State { IDLE, OBSERVING, READY }

    private State state = State.IDLE;
    private long lastInteractionTimestamp;
    private int interactionCountToday;
    private final Set<Integer> activeHours = new HashSet<>(); // hours of day (0-23) user is active
    private int historicalDailyAvg = 10; // rolling estimate
    private long idleThresholdMs = 2 * 60 * 60 * 1000L; // default 2 hours

    private final SharedPreferences prefs;

    public LifeEngine(Context context) {
        this.prefs = context.getApplicationContext()
                .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
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
            // If no active hours recorded yet (fresh contact), treat current hour as active
            boolean inActiveWindow = activeHours.isEmpty()
                    || activeHours.contains(hourOfDay(now));
            boolean engagementDropped = interactionCountToday < historicalDailyAvg * ENGAGEMENT_DROP_RATIO;
            boolean morningNoChat = hourOfDay(now) >= 10 && interactionCountToday == 0;

            if (idleTooLong && inActiveWindow) {
                state = State.READY;
            } else if (engagementDropped && interactionCountToday > 0) {
                state = State.READY;
            } else if (morningNoChat) {
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

        if (interactionCountToday == 0 && hourOfDay(now) >= 10) {
            reason = LifeEngineEvent.Reason.MORNING_CHECK_IN;
            hint = "用户今天还没有开始聊天，可以问候早安";
        } else if (interactionCountToday > 0
                && interactionCountToday < historicalDailyAvg * ENGAGEMENT_DROP_RATIO) {
            reason = LifeEngineEvent.Reason.ENGAGEMENT_DROP;
            hint = "用户今天的互动明显少于平常，可能心情不好或很忙";
        } else {
            reason = LifeEngineEvent.Reason.PROLONGED_IDLE;
            hint = "用户已经 " + idleMinutes + " 分钟没有互动了，通常在此时段活跃";
        }

        float confidence = Math.min(0.95f, idleMinutes / 480f); // scales to 0.95 over 8h

        // Transition back after firing
        state = State.OBSERVING;

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
            JSONArray hours = new JSONArray();
            for (int h : activeHours) hours.put(h);
            obj.put("activeHours", hours);
        } catch (Exception ignored) {}
        prefs.edit().putString(contactId, obj.toString()).apply();
    }

    public void load(String contactId) {
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
