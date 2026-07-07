package com.example.blankapp;

import java.util.List;

/**
 * @deprecated Replaced by {@link com.example.blankapp.orchestration.ProactiveOrchestrator}
 *             which uses LLM-driven decision, LifeEngine + EmotionEngine, and dynamic PersonaState.
 *             Kept for reference only; will be removed in a future cleanup.
 */
@Deprecated
public class ProactiveDialogueEngine {
    public String evaluateForProactiveMessage(String latestUserInput, PersonaState personaState, List<ChatMessage> history) {
        if (personaState == null) {
            return null;
        }
        if (personaState.busy) {
            return null;
        }
        if (!personaState.healthyRoutine) {
            return null;
        }

        boolean contextIsRich = history != null && history.size() >= 3;
        boolean emotionalSignal = (latestUserInput != null && latestUserInput.contains("担心"))
                || (latestUserInput != null && latestUserInput.contains("累"))
                || (latestUserInput != null && latestUserInput.contains("难"));
        boolean highDrive = personaState.energy > 0.6f && personaState.mood > 0.6f;
        int motivation = personaState.curiosity + personaState.care + personaState.sharing + personaState.memory;

        if (contextIsRich && highDrive && motivation >= 10) {
            if (emotionalSignal) {
                return "我注意到你最近在尝试一件重要的事，我想问一下：现在最需要的支持是什么？";
            }
            return "我注意到你刚刚在聊一件值得认真对待的事情，我想继续陪你把它聊清楚。";
        }

        if (personaState.energy > 0.8f && personaState.curiosity >= 3) {
            return "你刚刚提到的内容很有意思，我想继续听你讲下去。";
        }

        return null;
    }
}
