package com.example.blankapp;

import android.content.Context;
import android.content.SharedPreferences;

public class SettingsStore {
    private static final String PREFS_NAME = "companion_settings";
    private static final String KEY_API_KEY = "deepseek_api_key";
    private static final String KEY_SERVER_URL = "server_url";

    private final SharedPreferences prefs;

    public SettingsStore(Context context) {
        this.prefs = context != null
                ? context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                : null;
    }

    public void saveApiKey(String apiKey) {
        if (prefs == null) return;
        prefs.edit().putString(KEY_API_KEY, apiKey).apply();
    }

    public String getApiKey() {
        return prefs != null ? prefs.getString(KEY_API_KEY, "") : "";
    }

    public void saveServerUrl(String serverUrl) {
        if (prefs == null) return;
        prefs.edit().putString(KEY_SERVER_URL, serverUrl).apply();
    }

    public String getServerUrl() {
        return prefs != null ? prefs.getString(KEY_SERVER_URL, "http://10.0.2.2:8000") : "http://10.0.2.2:8000";
    }
}
