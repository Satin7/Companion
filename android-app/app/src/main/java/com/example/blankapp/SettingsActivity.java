package com.example.blankapp;

import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Toast;
import androidx.appcompat.app.AppCompatActivity;

public class SettingsActivity extends AppCompatActivity {
    private SettingsStore settingsStore;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_settings);

        settingsStore = new SettingsStore(this);

        EditText inputApiKey = findViewById(R.id.inputApiKey);
        EditText inputServerUrl = findViewById(R.id.inputServerUrl);
        Button saveButton = findViewById(R.id.btnSaveSettings);

        inputApiKey.setText(settingsStore.getApiKey());
        inputServerUrl.setText(settingsStore.getServerUrl());

        saveButton.setOnClickListener(v -> {
            settingsStore.saveApiKey(inputApiKey.getText().toString().trim());
            settingsStore.saveServerUrl(inputServerUrl.getText().toString().trim());
            Toast.makeText(this, "设置已保存", Toast.LENGTH_SHORT).show();
            finish();
        });
    }
}
