package com.example.blankapp;

public class ChatMessage {
    public final String role;
    public final String content;
    public final long timestamp;

    public ChatMessage(String role, String content) {
        this(role, content, System.currentTimeMillis());
    }

    public ChatMessage(String role, String content, long timestamp) {
        this.role = role;
        this.content = content;
        this.timestamp = timestamp;
    }
}
