package com.example.blankapp;

import static org.junit.Assert.assertEquals;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;

@RunWith(RobolectricTestRunner.class)
public class SettingsStoreTest {
    @Test
    public void storesAndReadsApiKey() {
        SettingsStore store = new SettingsStore(RuntimeEnvironment.getApplication());
        store.saveApiKey("test-key");
        assertEquals("test-key", store.getApiKey());
    }
}
