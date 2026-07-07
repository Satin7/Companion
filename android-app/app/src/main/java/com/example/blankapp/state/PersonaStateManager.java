package com.example.blankapp.state;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Manages loading, evolving, and persisting PersonaState.
 */
public class PersonaStateManager {

    private static final String PREFS_NAME = "persona_state";
    private final SharedPreferences prefs;
    private PersonaState current;

    public PersonaStateManager(Context context) {
        this.prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    /** Load persisted state for a contact, or return a fresh default. */
    public PersonaState load(String contactId) {
        String raw = prefs.getString(contactId, null);
        if (raw != null && !raw.isEmpty()) {
            current = PersonaState.fromJson(raw);
        } else {
            current = new PersonaState();
        }
        return current;
    }

    /** Return current in-memory state (never null after load()). */
    public PersonaState current() {
        if (current == null) {
            current = new PersonaState();
        }
        return current;
    }

    /** Persist current state. */
    public void persist(String contactId) {
        if (current == null) return;
        current.setLastUpdatedTimestamp(System.currentTimeMillis());
        prefs.edit().putString(contactId, current.toJson().toString()).apply();
    }

    // ── evolution helpers ───────────────────────────────────────

    /**
     * Nudge energy: increase with recent engagement, decay with idle time.
     *
     * @param engaged  true when user recently sent a message
     * @param idleMinutes  minutes since last user interaction
     */
    public void evolveEnergy(boolean engaged, long idleMinutes) {
        PersonaState s = current();
        if (engaged) {
            s.setEnergy(s.getEnergy() + 0.05f);
        } else {
            float decay = Math.min(0.3f, idleMinutes / 600f); // max decay over 3h
            s.setEnergy(s.getEnergy() - decay);
        }
    }

    /**
     * Nudge mood based on recent emotional valence from EmotionEngine.
     *
     * @param valence  -1.0 (negative) to +1.0 (positive)
     */
    public void evolveMood(float valence) {
        PersonaState s = current();
        float shift = valence * 0.1f;
        s.setMood(s.getMood() + shift);
    }

    /**
     * Adjust curiosity based on topic variety.
     */
    public void evolveCuriosity(boolean newTopicDetected) {
        PersonaState s = current();
        if (newTopicDetected) {
            s.setCuriosity(s.getCuriosity() + 1);
        }
    }

    /**
     * Adjust care based on user emotional state.
     *
     * @param userDistressed  true if user shows negative emotion
     */
    public void evolveCare(boolean userDistressed) {
        PersonaState s = current();
        if (userDistressed) {
            s.setCare(Math.min(5, s.getCare() + 1));
        }
    }

    /**
     * Nudge emotional resonance toward user's valence.
     */
    public void evolveEmotionalResonance(float userValence) {
        PersonaState s = current();
        float target = (userValence + 1f) / 2f; // map -1..1 to 0..1
        float current = s.getEmotionalResonance();
        s.setEmotionalResonance(current + (target - current) * 0.2f);
    }
}
