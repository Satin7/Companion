package com.example.blankapp;

import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import androidx.appcompat.app.AppCompatActivity;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.List;

public class ChatListActivity extends AppCompatActivity {
    private final List<ChatContact> contacts = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_chat_list);

        contacts.add(new ChatContact("companion", "Companion", "你今天想聊什么？", Color.parseColor("#4F46E5")));
        contacts.add(new ChatContact("study", "学习助手", "帮我整理今天的学习计划", Color.parseColor("#0F766E")));
        contacts.add(new ChatContact("life", "生活管家", "提醒我下午去取快递", Color.parseColor("#DC2626")));
        contacts.add(new ChatContact("test_proactive", "🧪 主动消息测试", "每1分钟自动发送主动消息", Color.parseColor("#F59E0B")));

        RecyclerView recyclerView = findViewById(R.id.recyclerContacts);
        recyclerView.setLayoutManager(new LinearLayoutManager(this));
        recyclerView.setAdapter(new ContactAdapter(contacts));

        findViewById(R.id.btnSettings).setOnClickListener(v -> {
            Intent intent = new Intent(this, SettingsActivity.class);
            startActivity(intent);
        });
    }

    private static class ContactAdapter extends RecyclerView.Adapter<ContactAdapter.ContactViewHolder> {
        private final List<ChatContact> contacts;

        ContactAdapter(List<ChatContact> contacts) {
            this.contacts = contacts;
        }

        @Override
        public ContactViewHolder onCreateViewHolder(ViewGroup parent, int viewType) {
            View view = LayoutInflater.from(parent.getContext()).inflate(R.layout.item_chat_contact, parent, false);
            return new ContactViewHolder(view);
        }

        @Override
        public void onBindViewHolder(ContactViewHolder holder, int position) {
            ChatContact contact = contacts.get(position);
            holder.avatar.setBackgroundColor(contact.avatarColor);
            holder.name.setText(contact.name);
            holder.preview.setText(contact.preview);
            holder.itemView.setOnClickListener(v -> {
                Intent intent = new Intent(v.getContext(), ChatDetailActivity.class);
                intent.putExtra("contact_id", contact.id);
                intent.putExtra("contact_name", contact.name);
                v.getContext().startActivity(intent);
            });
        }

        @Override
        public int getItemCount() {
            return contacts.size();
        }

        static class ContactViewHolder extends RecyclerView.ViewHolder {
            final ImageView avatar;
            final TextView name;
            final TextView preview;

            ContactViewHolder(View itemView) {
                super(itemView);
                avatar = itemView.findViewById(R.id.contactAvatar);
                name = itemView.findViewById(R.id.contactName);
                preview = itemView.findViewById(R.id.contactPreview);
            }
        }
    }
}
