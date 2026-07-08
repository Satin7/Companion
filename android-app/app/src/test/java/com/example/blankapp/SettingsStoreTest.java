package com.example.blankapp;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

/**
 * SettingsStore tests (no Robolectric required).
 * SettingsStore with null context simply returns defaults.
 */
public class SettingsStoreTest {
    @Test
    public void nullContextReturnsDefaults() {
        SettingsStore store = new SettingsStore(null);
        assertEquals("", store.getApiKey());
        assertEquals("http://10.0.2.2:8000", store.getServerUrl());
    }

    @Test
    public void saveAndRead_withNullContext_doesNotCrash() {
        SettingsStore store = new SettingsStore(null);
        store.saveApiKey("test-key");
        store.saveServerUrl("http://test:1234");
        // With null context, SharedPreferences is null — save/read won't persist
        // but shouldn't crash
    }
}
