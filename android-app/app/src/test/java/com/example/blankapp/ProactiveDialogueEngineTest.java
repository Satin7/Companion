package com.example.blankapp;

import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public class ProactiveDialogueEngineTest {
    @Test
    public void returnsNullWhenPersonaIsBusy() {
        ProactiveDialogueEngine engine = new ProactiveDialogueEngine();
        PersonaState state = new PersonaState();
        state.busy = true;
        state.healthyRoutine = true;
        List<ChatMessage> history = new ArrayList<>(Arrays.asList(
                new ChatMessage("user", "我今天很累")
        ));

        assertNull(engine.evaluateForProactiveMessage("我想休息一下", state, history));
    }

    @Test
    public void returnsMessageWhenPersonaIsHealthyAndContextIsRich() {
        ProactiveDialogueEngine engine = new ProactiveDialogueEngine();
        PersonaState state = new PersonaState();
        state.busy = false;
        state.healthyRoutine = true;
        state.energy = 0.8f;
        state.mood = 0.8f;
        List<ChatMessage> history = new ArrayList<>(Arrays.asList(
                new ChatMessage("user", "我刚开始做一个新项目"),
                new ChatMessage("assistant", "这听起来很有挑战性"),
                new ChatMessage("user", "我有点担心自己坚持不下去")
        ));

        assertNotNull(engine.evaluateForProactiveMessage("你现在还在吗", state, history));
    }
}
