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
import java.util.ArrayList;
import java.util.List;

public class ChatDetailActivity extends AppCompatActivity {
    private final List<ChatMessage> messages = new ArrayList<>();
    private final PersonaState personaState = new PersonaState();
    private final ProactiveDialogueEngine proactiveEngine = new ProactiveDialogueEngine();
    private final DeepSeekClient deepSeekClient = new DeepSeekClient();
    private SettingsStore settingsStore;
    private String contactName;
    private String contactId;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        settingsStore = new SettingsStore(this);
        setContentView(R.layout.activity_chat_detail);

        contactName = getIntent().getStringExtra("contact_name");
        contactId = getIntent().getStringExtra("contact_id");
        TextView title = findViewById(R.id.chatTitle);
        title.setText(contactName != null ? contactName : "聊天");

        LinearLayout messageContainer = findViewById(R.id.messageContainer);
        if (messages.isEmpty()) {
            List<ChatMessage> stored = ChatHistoryStore.loadMessages(this, contactId != null ? contactId : "default");
            if (!stored.isEmpty()) {
                messages.addAll(stored);
            } else {
                messages.add(new ChatMessage("assistant", "你好，我是 " + (contactName != null ? contactName : "Companion") + "。你可以开始聊天。"));
            }
        }
        renderMessages(messageContainer);
        ScrollView scrollView = findViewById(R.id.chatScrollView);
        scrollView.post(() -> scrollView.fullScroll(ScrollView.FOCUS_DOWN));

        EditText input = findViewById(R.id.inputMessage);
        Button sendButton = findViewById(R.id.btnSend);
        sendButton.setOnClickListener(v -> {
            String text = input.getText().toString().trim();
            if (text.isEmpty()) return;

            messages.add(new ChatMessage("user", text));
            ChatHistoryStore.saveMessages(ChatDetailActivity.this, contactId != null ? contactId : "default", messages);
            renderMessages(messageContainer);
            scrollView.post(() -> scrollView.fullScroll(ScrollView.FOCUS_DOWN));
            input.setText("");

            String prompt = "你是一个温暖、理性且有主动关心能力的助手。请简短地回复用户，并在适合时表达关心。用户说：" + text;
            deepSeekClient.complete(settingsStore.getApiKey(), prompt, new DeepSeekClient.Callback() {
                @Override
                public void onSuccess(String reply) {
                    messages.add(new ChatMessage("assistant", reply));
                    ChatHistoryStore.saveMessages(ChatDetailActivity.this, contactId != null ? contactId : "default", messages);
                    renderMessages(messageContainer);
                    scrollView.post(() -> scrollView.fullScroll(ScrollView.FOCUS_DOWN));

                    String proactive = proactiveEngine.evaluateForProactiveMessage(text, personaState, messages);
                    if (proactive != null) {
                        messages.add(new ChatMessage("assistant", "[主动关心] " + proactive));
                        ChatHistoryStore.saveMessages(ChatDetailActivity.this, contactId != null ? contactId : "default", messages);
                        renderMessages(messageContainer);
                        scrollView.post(() -> scrollView.fullScroll(ScrollView.FOCUS_DOWN));
                    }
                }

                @Override
                public void onError(String error) {
                    messages.add(new ChatMessage("assistant", "抱歉，当前无法连接到 DeepSeek 服务：" + error));
                    ChatHistoryStore.saveMessages(ChatDetailActivity.this, contactId != null ? contactId : "default", messages);
                    renderMessages(messageContainer);
                    scrollView.post(() -> scrollView.fullScroll(ScrollView.FOCUS_DOWN));
                }
            });
        });
    }

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
            bubble.setBackgroundColor(message.role.equals("user") ? Color.parseColor("#4F46E5") : Color.parseColor("#FFFFFF"));
            bubble.setElevation(2f);

            TextView textView = new TextView(this);
            textView.setText(message.content);
            textView.setTextSize(15);
            textView.setTextColor(message.role.equals("user") ? Color.WHITE : Color.BLACK);
            textView.setMaxWidth(800);
            bubble.addView(textView);

            TextView meta = new TextView(this);
            meta.setTextSize(11);
            meta.setTextColor(message.role.equals("user") ? Color.parseColor("#E0E7FF") : Color.parseColor("#6B7280"));
            meta.setText(android.text.format.DateFormat.format("MM-dd HH:mm", message.timestamp).toString());
            bubble.addView(meta);

            wrapper.addView(bubble);
            container.addView(wrapper);
        }
    }
}
