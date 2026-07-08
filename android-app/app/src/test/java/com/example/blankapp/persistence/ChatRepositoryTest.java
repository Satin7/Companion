package com.example.blankapp.persistence;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import com.example.blankapp.ChatMessage;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public class ChatRepositoryTest {

    @Test
    public void encodeDecodeRoundtrip() {
        List<ChatMessage> original = new ArrayList<>(Arrays.asList(
                new ChatMessage("user", "你好", 1000L),
                new ChatMessage("assistant", "你好！有什么可以帮你的？", 2000L),
                new ChatMessage("user", "今天天气很好", 3000L)
        ));

        String encoded = ChatRepository.encode(original);
        List<ChatMessage> decoded = ChatRepository.decode(encoded);

        assertEquals(original.size(), decoded.size());
        for (int i = 0; i < original.size(); i++) {
            assertEquals(original.get(i).role, decoded.get(i).role);
            assertEquals(original.get(i).content, decoded.get(i).content);
            assertEquals(original.get(i).timestamp, decoded.get(i).timestamp);
        }
    }

    @Test
    public void decodeEmptyString() {
        assertTrue(ChatRepository.decode("").isEmpty());
    }

    @Test
    public void decodeEmptyArray() {
        assertTrue(ChatRepository.decode("[]").isEmpty());
    }

    @Test
    public void encodeEmptyList() {
        assertEquals("[]", ChatRepository.encode(new ArrayList<>()));
    }

    @Test
    public void messagesWithChineseContent() {
        List<ChatMessage> msgs = new ArrayList<>(Arrays.asList(
                new ChatMessage("user", "我今天感觉很累", 1000L),
                new ChatMessage("assistant", "听起来你需要休息一下。要聊聊吗？", 2000L)
        ));
        String encoded = ChatRepository.encode(msgs);
        List<ChatMessage> decoded = ChatRepository.decode(encoded);
        assertEquals(2, decoded.size());
        assertEquals("我今天感觉很累", decoded.get(0).content);
        assertEquals("听起来你需要休息一下。要聊聊吗？", decoded.get(1).content);
    }

    @Test
    public void emojiRoundtrip() {
        List<ChatMessage> msgs = new ArrayList<>(Arrays.asList(
                new ChatMessage("user", "hello 😀 world", 1000L)
        ));
        String encoded = ChatRepository.encode(msgs);
        List<ChatMessage> decoded = ChatRepository.decode(encoded);
        assertEquals(1, decoded.size());
        assertEquals("hello 😀 world", decoded.get(0).content);
    }
}
