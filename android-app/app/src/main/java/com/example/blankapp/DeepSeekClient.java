package com.example.blankapp;

import android.os.Handler;
import android.os.Looper;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

public class DeepSeekClient {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    public interface Callback {
        void onSuccess(String reply);
        void onError(String error);
    }

    public void complete(String apiKey, String prompt, Callback callback) {
        executor.execute(() -> {
            try {
                URL url = new URL("https://api.deepseek.com/chat/completions");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setRequestProperty("Authorization", "Bearer " + apiKey);
                conn.setDoOutput(true);

                JSONObject body = new JSONObject();
                body.put("model", "deepseek-v4-pro");

                org.json.JSONArray messages = new org.json.JSONArray();
                messages.put(new JSONObject().put("role", "system").put("content", "You are a helpful assistant."));
                messages.put(new JSONObject().put("role", "user").put("content", prompt));
                body.put("messages", messages);

                JSONObject thinking = new JSONObject();
                thinking.put("type", "enabled");
                body.put("thinking", thinking);
                body.put("reasoning_effort", "high");
                body.put("stream", false);

                byte[] payload = body.toString().getBytes(StandardCharsets.UTF_8);
                conn.setFixedLengthStreamingMode(payload.length);
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(payload);
                }

                int code = conn.getResponseCode();
                if (code >= 400) {
                    String error = new java.util.Scanner(conn.getErrorStream(), StandardCharsets.UTF_8).useDelimiter("\\A").next();
                    mainHandler.post(() -> callback.onError(error));
                    return;
                }

                String response = new java.util.Scanner(conn.getInputStream(), StandardCharsets.UTF_8).useDelimiter("\\A").next();
                JSONObject root = new JSONObject(response);
                String content = root.getJSONArray("choices").getJSONObject(0).getJSONObject("message").getString("content");
                mainHandler.post(() -> callback.onSuccess(content));
            } catch (Exception e) {
                mainHandler.post(() -> callback.onError(e.getMessage()));
            }
        });
    }
}
