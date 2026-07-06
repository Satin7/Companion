package com.example.blankapp;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.ArrayList;
import java.util.List;

public class ChatHistoryStore {
    private static final String PREFS_NAME = "chat_history";

    public static String encodeMessages(List<ChatMessage> messages) {
        StringBuilder builder = new StringBuilder();
        for (ChatMessage message : messages) {
            if (builder.length() > 0) {
                builder.append("\n");
            }
            builder.append(message.role)
                    .append("||")
                    .append(message.content.replace("\n", "\\n").replace("||", "\\|\\|"))
                    .append("||")
                    .append(message.timestamp);
        }
        return builder.toString();
    }

    public static List<ChatMessage> decodeMessages(String data) {
        List<ChatMessage> result = new ArrayList<>();
        if (data == null || data.trim().isEmpty()) {
            return result;
        }
        String[] lines = data.split("\\n");
        for (String line : lines) {
            if (line.trim().isEmpty()) {
                continue;
            }
            String[] parts = line.split("\\|\\|", 3);
            if (parts.length >= 3) {
                String role = parts[0];
                String content = parts[1].replace("\\n", "\n").replace("\\|\\|", "||");
                long timestamp = Long.parseLong(parts[2]);
                result.add(new ChatMessage(role, content, timestamp));
            }
        }
        return result;
    }

    public static void saveMessages(Context context, String key, List<ChatMessage> messages) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        prefs.edit().putString(key, encodeMessages(messages)).apply();
    }

    public static List<ChatMessage> loadMessages(Context context, String key) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        return decodeMessages(prefs.getString(key, ""));
    }
}
