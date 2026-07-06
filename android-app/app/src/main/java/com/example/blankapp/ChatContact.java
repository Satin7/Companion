package com.example.blankapp;

public class ChatContact {
    public final String id;
    public final String name;
    public final String preview;
    public final int avatarColor;

    public ChatContact(String id, String name, String preview, int avatarColor) {
        this.id = id;
        this.name = name;
        this.preview = preview;
        this.avatarColor = avatarColor;
    }
}
