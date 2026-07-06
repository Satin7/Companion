package com.example.blankapp;

import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
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
    private final SettingsStore settingsStore = new SettingsStore(this);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_chat_detail);

        String contactName = getIntent().getStringExtra("contact_name");
        TextView title = findViewById(R.id.chatTitle);
        title.setText(contactName != null ? contactName : "聊天");

        LinearLayout messageContainer = findViewById(R.id.messageContainer);
        messages.add(new ChatMessage("assistant", "你好，我是 " + (contactName != null ? contactName : "Companion") + "。你可以开始聊天。"));
        renderMessages(messageContainer);

        EditText input = findViewById(R.id.inputMessage);
        Button sendButton = findViewById(R.id.btnSend);
        sendButton.setOnClickListener(v -> {
            String text = input.getText().toString().trim();
            if (text.isEmpty()) return;

            messages.add(new ChatMessage("user", text));
            renderMessages(messageContainer);
            input.setText("");

            String prompt = "你是一个温暖、理性且有主动关心能力的助手。请简短地回复用户，并在适合时表达关心。用户说：" + text;
            deepSeekClient.complete(settingsStore.getApiKey(), prompt, new DeepSeekClient.Callback() {
                @Override
                public void onSuccess(String reply) {
                    messages.add(new ChatMessage("assistant", reply));
                    renderMessages(messageContainer);

                    String proactive = proactiveEngine.evaluateForProactiveMessage(text, personaState, messages);
                    if (proactive != null) {
                        messages.add(new ChatMessage("assistant", proactive));
                        renderMessages(messageContainer);
                    }
                }

                @Override
                public void onError(String error) {
                    messages.add(new ChatMessage("assistant", "抱歉，当前无法连接到 DeepSeek 服务：" + error));
                    renderMessages(messageContainer);
                }
            });
        });
    }

    private void renderMessages(LinearLayout container) {
        container.removeAllViews();
        for (ChatMessage message : messages) {
            LinearLayout bubble = new LinearLayout(this);
            bubble.setOrientation(LinearLayout.HORIZONTAL);
            bubble.setGravity(message.role.equals("user") ? Gravity.END : Gravity.START);
            bubble.setPadding(0, 6, 0, 6);

            TextView textView = new TextView(this);
            textView.setText(message.content);
            textView.setTextSize(15);
            textView.setPadding(16, 12, 16, 12);
            textView.setTextColor(message.role.equals("user") ? Color.WHITE : Color.BLACK);
            textView.setBackgroundColor(message.role.equals("user") ? Color.parseColor("#4F46E5") : Color.WHITE);
            textView.setMaxWidth(800);
            bubble.addView(textView);
            container.addView(bubble);
        }
    }
}
