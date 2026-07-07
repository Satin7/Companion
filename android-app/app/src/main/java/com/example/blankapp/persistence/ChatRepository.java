package com.example.blankapp.persistence;

import android.content.Context;
import android.content.SharedPreferences;

import com.example.blankapp.ChatMessage;
import com.example.blankapp.ChatHistoryStore;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * JSON-backed chat persistence, replaces the brittle delimiter-based ChatHistoryStore.
 *
 * Each conversation (keyed by contactId) is stored as a JSON array string in
 * SharedPreferences. Old pipe-delimited format is auto-migrated on first load.
 */
public class ChatRepository {

    private static final String PREFS_NAME = "chat_data_json";
    private static final int MAX_MESSAGES = 500;

    private final Context context;
    private final SharedPreferences prefs;

    public ChatRepository(Context context) {
        this.context = context.getApplicationContext();
        this.prefs = this.context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    // ── public API ──────────────────────────────────────────────

    public List<ChatMessage> loadMessages(String contactId) {
        String raw = prefs.getString(contactId, null);
        if (raw == null || raw.trim().isEmpty()) {
            // Try migration from old ChatHistoryStore format
            List<ChatMessage> migrated = ChatHistoryStore.loadMessages(context, contactId);
            if (!migrated.isEmpty()) {
                saveMessages(contactId, migrated);
            }
            return migrated;
        }
        return decode(raw);
    }

    public void saveMessages(String contactId, List<ChatMessage> messages) {
        List<ChatMessage> trimmed = messages;
        if (messages.size() > MAX_MESSAGES) {
            trimmed = new ArrayList<>(messages.subList(messages.size() - MAX_MESSAGES, messages.size()));
        }
        prefs.edit().putString(contactId, encode(trimmed)).apply();
    }

    public void appendMessage(String contactId, ChatMessage message) {
        List<ChatMessage> existing = loadMessages(contactId);
        existing.add(message);
        saveMessages(contactId, existing);
    }

    // ── encode / decode ─────────────────────────────────────────

    static String encode(List<ChatMessage> messages) {
        JSONArray arr = new JSONArray();
        for (ChatMessage m : messages) {
            JSONObject obj = new JSONObject();
            try {
                obj.put("role", m.role);
                obj.put("content", m.content);
                obj.put("timestamp", m.timestamp);
                arr.put(obj);
            } catch (Exception ignored) {
            }
        }
        return arr.toString();
    }

    static List<ChatMessage> decode(String raw) {
        List<ChatMessage> result = new ArrayList<>();
        try {
            JSONArray arr = new JSONArray(raw);
            for (int i = 0; i < arr.length(); i++) {
                JSONObject obj = arr.getJSONObject(i);
                String role = obj.optString("role", "assistant");
                String content = obj.optString("content", "");
                long timestamp = obj.optLong("timestamp", System.currentTimeMillis());
                result.add(new ChatMessage(role, content, timestamp));
            }
        } catch (Exception ignored) {
        }
        return result;
    }
}
