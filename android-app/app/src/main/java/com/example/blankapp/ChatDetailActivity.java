package com.example.blankapp;

import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import androidx.appcompat.app.AppCompatActivity;
import java.util.ArrayList;
import java.util.List;

public class ChatDetailActivity extends AppCompatActivity {
    private final List<String> messages = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_chat_detail);

        String contactName = getIntent().getStringExtra("contact_name");
        TextView title = findViewById(R.id.chatTitle);
        title.setText(contactName != null ? contactName : "聊天");

        LinearLayout messageContainer = findViewById(R.id.messageContainer);
        messages.add("你好，我是 " + contactName + "。你可以开始聊天。" );
        renderMessages(messageContainer);

        EditText input = findViewById(R.id.inputMessage);
        Button sendButton = findViewById(R.id.btnSend);
        sendButton.setOnClickListener(v -> {
            String text = input.getText().toString().trim();
            if (text.isEmpty()) return;
            messages.add("你：" + text);
            messages.add("助手：我已经收到你的消息：" + text);
            input.setText("");
            renderMessages(messageContainer);
        });
    }

    private void renderMessages(LinearLayout container) {
        container.removeAllViews();
        for (String message : messages) {
            TextView textView = new TextView(this);
            textView.setText(message);
            textView.setPadding(24, 12, 24, 12);
            textView.setTextSize(15);
            container.addView(textView);
        }
    }
}
