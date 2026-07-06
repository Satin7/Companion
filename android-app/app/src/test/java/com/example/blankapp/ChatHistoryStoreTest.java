package com.example.blankapp;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Arrays;
import java.util.List;

public class ChatHistoryStoreTest {
    @Test
    public void roundTripsMessagesWithEncodingAndDecoding() {
        List<ChatMessage> messages = Arrays.asList(
                new ChatMessage("user", "你好"),
                new ChatMessage("assistant", "我在呢")
        );

        String encoded = ChatHistoryStore.encodeMessages(messages);
        List<ChatMessage> decoded = ChatHistoryStore.decodeMessages(encoded);

        assertEquals(2, decoded.size());
        assertEquals("你好", decoded.get(0).content);
        assertEquals("assistant", decoded.get(1).role);
        assertTrue(decoded.get(1).timestamp > 0);
    }
}
