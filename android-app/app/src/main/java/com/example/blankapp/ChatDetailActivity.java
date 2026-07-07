package com.example.blankapp;

import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.ScrollView;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import androidx.appcompat.app.AppCompatActivity;

import com.example.blankapp.client.DeepSeekClient;
import com.example.blankapp.client.DeepSeekRequest;
import com.example.blankapp.orchestration.ProactiveOrchestrator;
import com.example.blankapp.persistence.ChatRepository;

import java.util.ArrayList;
import java.util.List;

public class ChatDetailActivity extends AppCompatActivity {
    private final List<ChatMessage> messages = new ArrayList<>();
    private final DeepSeekClient deepSeekClient = new DeepSeekClient();
    private SettingsStore settingsStore;
    private ChatRepository chatRepo;
    private ProactiveOrchestrator orchestrator;
    private String contactName;
    private String contactId;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        settingsStore = new SettingsStore(this);
        chatRepo = new ChatRepository(this);
        setContentView(R.layout.activity_chat_detail);

        contactName = getIntent().getStringExtra("contact_name");
        contactId = getIntent().getStringExtra("contact_id");
        String id = contactId != null ? contactId : "default";
        TextView title = findViewById(R.id.chatTitle);
        title.setText(contactName != null ? contactName : "聊天");

        // Init orchestrator
        orchestrator = new ProactiveOrchestrator(this, id, deepSeekClient);
        orchestrator.configure(settingsStore.getApiKey(), orchestratorCallback);

        // Test mode: "test_proactive" contact sends proactive messages every ~1 minute
        if ("test_proactive".equals(contactId)) {
            orchestrator.enableTestMode();
        }

        // Load messages
        LinearLayout messageContainer = findViewById(R.id.messageContainer);
        if (messages.isEmpty()) {
            List<ChatMessage> stored = chatRepo.loadMessages(id);
            if (!stored.isEmpty()) {
                messages.addAll(stored);
            } else {
                messages.add(new ChatMessage("assistant",
                        "你好，我是 " + (contactName != null ? contactName : "Companion") + "。你可以开始聊天。"));
            }
        }
        renderMessages(messageContainer);
        ScrollView scrollView = findViewById(R.id.chatScrollView);
        scrollView.post(() -> scrollView.fullScroll(ScrollView.FOCUS_DOWN));

        // Send button
        EditText input = findViewById(R.id.inputMessage);
        Button sendButton = findViewById(R.id.btnSend);
        sendButton.setOnClickListener(v -> {
            String text = input.getText().toString().trim();
            if (text.isEmpty()) return;

            String apiKey = settingsStore.getApiKey();
            messages.add(new ChatMessage("user", text));
            chatRepo.saveMessages(id, messages);
            renderMessages(messageContainer);
            scrollView.post(() -> scrollView.fullScroll(ScrollView.FOCUS_DOWN));
            input.setText("");

            // Build main reply request
            String systemPrompt = "你是一个温暖、理性且有主动关心能力的助手。请简短地回复用户，并在适合时表达关心。用户说：";
            DeepSeekRequest replyReq = DeepSeekRequest.replyGeneration(systemPrompt, text);

            deepSeekClient.complete(apiKey, replyReq, new DeepSeekClient.Callback() {
                @Override
                public void onSuccess(String reply) {
                    messages.add(new ChatMessage("assistant", reply));
                    chatRepo.saveMessages(id, messages);
                    renderMessages(messageContainer);
                    scrollView.post(() -> scrollView.fullScroll(ScrollView.FOCUS_DOWN));

                    // Post-reply proactive evaluation
                    orchestrator.configure(apiKey, orchestratorCallback);
                    orchestrator.evaluatePostReply(apiKey, messages, text, orchestratorCallback);
                }

                @Override
                public void onError(String error) {
                    messages.add(new ChatMessage("assistant", "抱歉，当前无法连接到 DeepSeek 服务：" + error));
                    chatRepo.saveMessages(id, messages);
                    renderMessages(messageContainer);
                    scrollView.post(() -> scrollView.fullScroll(ScrollView.FOCUS_DOWN));
                }
            });
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        orchestrator.configure(settingsStore.getApiKey(), orchestratorCallback);
        orchestrator.resume();
    }

    @Override
    protected void onPause() {
        super.onPause();
        orchestrator.pause();
    }

    // ── orchestrator callback ────────────────────────────────────

    private final ProactiveOrchestrator.Callback orchestratorCallback = new ProactiveOrchestrator.Callback() {
        @Override
        public void onProactiveMessageReady(String proactiveMessage) {
            String id = contactId != null ? contactId : "default";
            messages.add(new ChatMessage("assistant", "[主动关心] " + proactiveMessage));
            chatRepo.saveMessages(id, messages);

            LinearLayout container = findViewById(R.id.messageContainer);
            if (container != null) {
                renderMessages(container);
                ScrollView sv = findViewById(R.id.chatScrollView);
                if (sv != null) sv.post(() -> sv.fullScroll(ScrollView.FOCUS_DOWN));
            }
        }

        @Override
        public void onNoAction() {
            // Nothing needed
        }

        @Override
        public void onError(String error) {
            // Silent degradation for proactive errors
        }
    };

    // ── render ───────────────────────────────────────────────────

    private void renderMessages(LinearLayout container) {
        container.removeAllViews();
        for (ChatMessage message : messages) {
            LinearLayout wrapper = new LinearLayout(this);
            wrapper.setOrientation(LinearLayout.HORIZONTAL);
            wrapper.setGravity(message.role.equals("user") ? Gravity.END : Gravity.START);
            wrapper.setPadding(0, 6, 0, 6);

            LinearLayout bubble = new LinearLayout(this);
            bubble.setOrientation(LinearLayout.VERTICAL);
            bubble.setPadding(14, 10, 14, 10);
            bubble.setBackgroundColor(message.role.equals("user")
                    ? Color.parseColor("#4F46E5") : Color.parseColor("#FFFFFF"));
            bubble.setElevation(2f);

            TextView textView = new TextView(this);
            textView.setText(message.content);
            textView.setTextSize(15);
            textView.setTextColor(message.role.equals("user") ? Color.WHITE : Color.BLACK);
            textView.setMaxWidth(800);
            bubble.addView(textView);

            TextView meta = new TextView(this);
            meta.setTextSize(11);
            meta.setTextColor(message.role.equals("user")
                    ? Color.parseColor("#E0E7FF") : Color.parseColor("#6B7280"));
            meta.setText(android.text.format.DateFormat.format("MM-dd HH:mm", message.timestamp).toString());
            bubble.addView(meta);

            wrapper.addView(bubble);
            container.addView(wrapper);
        }
    }
}
