package com.example.blankapp.state;

import org.json.JSONObject;

/**
 * Dynamic persona state that evolves with conversation.
 *
 * Fields are private with getters; mutation only through PersonaStateManager.
 * Supports JSON serialisation for SharedPreferences persistence.
 */
public class PersonaState {

    // ── core fields ─────────────────────────────────────────────

    private boolean busy;
    private float energy;        // 0.0 – 1.0
    private float mood;          // 0.0 – 1.0
    private int curiosity;       // 1 – 5
    private int care;            // 1 – 5
    private int sharing;         // 1 – 5
    private int memory;          // 1 – 5

    // ── new fields ──────────────────────────────────────────────

    private float openness;           // 0.0 – 1.0, topic variety
    private float emotionalResonance; // 0.0 – 1.0, alignment with user emotion
    private long lastUpdatedTimestamp;

    // ── defaults ────────────────────────────────────────────────

    public PersonaState() {
        this.busy = false;
        this.energy = 0.7f;
        this.mood = 0.7f;
        this.curiosity = 3;
        this.care = 3;
        this.sharing = 3;
        this.memory = 3;
        this.openness = 0.5f;
        this.emotionalResonance = 0.5f;
        this.lastUpdatedTimestamp = System.currentTimeMillis();
    }

    // ── getters ─────────────────────────────────────────────────

    public boolean isBusy()              { return busy; }
    public float getEnergy()             { return energy; }
    public float getMood()               { return mood; }
    public int getCuriosity()            { return curiosity; }
    public int getCare()                 { return care; }
    public int getSharing()              { return sharing; }
    public int getMemory()               { return memory; }
    public float getOpenness()           { return openness; }
    public float getEmotionalResonance() { return emotionalResonance; }
    public long getLastUpdatedTimestamp(){ return lastUpdatedTimestamp; }

    // ── setters (package-private — only PersonaStateManager) ────

    void setBusy(boolean v)              { this.busy = v; }
    void setEnergy(float v)              { this.energy = clamp(v, 0f, 1f); }
    void setMood(float v)                { this.mood = clamp(v, 0f, 1f); }
    void setCuriosity(int v)             { this.curiosity = clamp(v, 1, 5); }
    void setCare(int v)                  { this.care = clamp(v, 1, 5); }
    void setSharing(int v)               { this.sharing = clamp(v, 1, 5); }
    void setMemory(int v)                { this.memory = clamp(v, 1, 5); }
    void setOpenness(float v)            { this.openness = clamp(v, 0f, 1f); }
    void setEmotionalResonance(float v)  { this.emotionalResonance = clamp(v, 0f, 1f); }
    void setLastUpdatedTimestamp(long v) { this.lastUpdatedTimestamp = v; }

    // ── composite queries ───────────────────────────────────────

    /** Combined motivation score (4–20), used by trigger evaluation. */
    public int getMotivation() {
        return curiosity + care + sharing + memory;
    }

    /** True if persona is receptive to initiating conversation. */
    public boolean isReceptive() {
        return !busy && energy > 0.4f && mood > 0.3f;
    }

    // ── serialisation ───────────────────────────────────────────

    public JSONObject toJson() {
        JSONObject obj = new JSONObject();
        try {
            obj.put("busy", busy);
            obj.put("energy", (double) energy);
            obj.put("mood", (double) mood);
            obj.put("curiosity", curiosity);
            obj.put("care", care);
            obj.put("sharing", sharing);
            obj.put("memory", memory);
            obj.put("openness", (double) openness);
            obj.put("emotionalResonance", (double) emotionalResonance);
            obj.put("lastUpdated", lastUpdatedTimestamp);
        } catch (Exception ignored) {
        }
        return obj;
    }

    public static PersonaState fromJson(String raw) {
        PersonaState s = new PersonaState();
        try {
            JSONObject obj = new JSONObject(raw);
            s.busy = obj.optBoolean("busy", false);
            s.energy = (float) obj.optDouble("energy", 0.7);
            s.mood = (float) obj.optDouble("mood", 0.7);
            s.curiosity = obj.optInt("curiosity", 3);
            s.care = obj.optInt("care", 3);
            s.sharing = obj.optInt("sharing", 3);
            s.memory = obj.optInt("memory", 3);
            s.openness = (float) obj.optDouble("openness", 0.5);
            s.emotionalResonance = (float) obj.optDouble("emotionalResonance", 0.5);
            s.lastUpdatedTimestamp = obj.optLong("lastUpdated", System.currentTimeMillis());
        } catch (Exception ignored) {
        }
        return s;
    }

    public PersonaState copy() {
        return fromJson(toJson().toString());
    }

    // ── util ────────────────────────────────────────────────────

    private static float clamp(float v, float lo, float hi) {
        return Math.max(lo, Math.min(hi, v));
    }

    private static int clamp(int v, int lo, int hi) {
        return Math.max(lo, Math.min(hi, v));
    }
}
