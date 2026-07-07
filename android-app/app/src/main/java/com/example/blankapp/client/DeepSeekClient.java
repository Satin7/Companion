package com.example.blankapp.client;

import android.os.Handler;
import android.os.Looper;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import org.json.JSONObject;

/**
 * Hardened DeepSeek API client.
 *
 * Improvements over the old client:
 * - Configurable connect/read timeouts
 * - Request object pattern (DeepSeekRequest instead of raw prompt string)
 * - Single retry on timeout or 5xx
 * - Backward-compatible convenience overload
 */
public class DeepSeekClient {

    private static final int CONNECT_TIMEOUT_MS = 10_000;
    private static final int READ_TIMEOUT_MS = 30_000;
    private static final int MAX_RETRIES = 1;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    public interface Callback {
        void onSuccess(String reply);
        void onError(String error);
    }

    // ── new API: request object ─────────────────────────────────

    public void complete(String apiKey, DeepSeekRequest request, Callback callback) {
        executor.execute(() -> executeWithRetry(apiKey, request, callback, 0));
    }

    // ── backward-compatible convenience ─────────────────────────

    public void complete(String apiKey, String prompt, Callback callback) {
        DeepSeekRequest req = new DeepSeekRequest.Builder()
                .messages(makeSingleMessageArray(prompt))
                .reasoningEffort("high")
                .build();
        complete(apiKey, req, callback);
    }

    // ── internal ────────────────────────────────────────────────

    private void executeWithRetry(String apiKey, DeepSeekRequest request, Callback callback, int attempt) {
        try {
            String result = execute(apiKey, request);
            mainHandler.post(() -> callback.onSuccess(result));
        } catch (Exception e) {
            if (attempt < MAX_RETRIES && isRetryable(e)) {
                try { Thread.sleep(1000); } catch (InterruptedException ignored) {}
                executeWithRetry(apiKey, request, callback, attempt + 1);
            } else {
                mainHandler.post(() -> callback.onError(e.getMessage()));
            }
        }
    }

    private String execute(String apiKey, DeepSeekRequest request) throws Exception {
        URL url = new URL("https://api.deepseek.com/chat/completions");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setRequestProperty("Authorization", "Bearer " + apiKey);
        conn.setDoOutput(true);
        conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
        conn.setReadTimeout(READ_TIMEOUT_MS);

        byte[] payload = request.toJson().toString().getBytes(StandardCharsets.UTF_8);
        conn.setFixedLengthStreamingMode(payload.length);
        try (OutputStream os = conn.getOutputStream()) {
            os.write(payload);
        }

        int code = conn.getResponseCode();
        if (code >= 400) {
            String error = readStream(conn.getErrorStream());
            throw new RuntimeException("HTTP " + code + ": " + error);
        }

        String raw = readStream(conn.getInputStream());
        return parseContent(raw);
    }

    private String readStream(java.io.InputStream stream) {
        if (stream == null) return "";
        java.util.Scanner s = new java.util.Scanner(stream, StandardCharsets.UTF_8.name()).useDelimiter("\\A");
        return s.hasNext() ? s.next() : "";
    }

    /**
     * Extract choices[0].message.content from the DeepSeek API response JSON.
     * Only returns the final reply text; reasoning_content, id, system_fingerprint
     * etc. are discarded.
     */
    static String parseContent(String raw) {
        try {
            JSONObject root = new JSONObject(raw);
            return root.getJSONArray("choices")
                    .getJSONObject(0)
                    .getJSONObject("message")
                    .getString("content");
        } catch (Exception e) {
            // If parsing fails, return raw so the caller can see what went wrong
            return raw;
        }
    }

    private boolean isRetryable(Exception e) {
        String msg = e.getMessage();
        if (msg == null) return false;
        return msg.contains("timeout") || msg.contains("TimedOut")
                || msg.contains("500") || msg.contains("502")
                || msg.contains("503") || msg.contains("504");
    }

    private static org.json.JSONArray makeSingleMessageArray(String prompt) {
        org.json.JSONArray arr = new org.json.JSONArray();
        try {
            JSONObject sys = new JSONObject();
            sys.put("role", "system");
            sys.put("content", "You are a helpful assistant.");
            arr.put(sys);
            JSONObject user = new JSONObject();
            user.put("role", "user");
            user.put("content", prompt);
            arr.put(user);
        } catch (Exception ignored) {}
        return arr;
    }
}
