package com.example.blankapp.orchestration;

import android.content.Context;
import android.util.Log;

import com.example.blankapp.ChatMessage;
import com.example.blankapp.client.DeepSeekClient;
import com.example.blankapp.client.TriggerDecision;
import com.example.blankapp.client.TriggerDecisionClient;
import com.example.blankapp.engine.EmotionEngine;
import com.example.blankapp.engine.EmotionEngineEvent;
import com.example.blankapp.engine.LifeEngine;
import com.example.blankapp.engine.LifeEngineEvent;
import com.example.blankapp.persistence.ChatRepository;
import com.example.blankapp.scheduler.TriggerScheduler;
import com.example.blankapp.state.PersonaState;
import com.example.blankapp.state.PersonaStateManager;

import java.util.List;

/**
 * Central coordinator for the proactive dialogue system.
 *
 * Owns both engines, the persona state manager, the trigger decision client,
 * the scheduler, and the chat repository. Orchestrates the full pipeline:
 *
 *   Engine signals → LLM decision → LLM generation → callback
 *
 * Two entry points:
 * - evaluatePostReply(): called after each AI reply
 * - onTimerTick(): called periodically by TriggerScheduler
 */
public class ProactiveOrchestrator {

    private static final String TAG = "ProactiveOrch";

    private final String contactId;
    private final DeepSeekClient llmClient;
    private final TriggerDecisionClient decisionClient;
    private final LifeEngine lifeEngine;
    private final EmotionEngine emotionEngine;
    private final PersonaStateManager personaManager;
    private final ChatRepository chatRepo;
    private final TriggerScheduler scheduler;

    private String apiKey;
    private Callback defaultCallback;
    private List<ChatMessage> cachedMessages; // reference to ChatDetailActivity's list

    // ── cached messages setter ──────────────────────────────────

    /**
     * Set the cached message list reference so the timer tick has context to
     * evaluate triggers. Call this after loading messages in onCreate/onResume.
     */
    public void setCachedMessages(List<ChatMessage> messages) {
        this.cachedMessages = messages;
    }

    // ── callback ────────────────────────────────────────────────

    public interface Callback {
        /** A proactive message was generated and should be displayed. */
        void onProactiveMessageReady(String message);
        /** No action needed at this time. */
        void onNoAction();
        /** An error occurred during the pipeline. */
        void onError(String error);
    }

    // ── construction ────────────────────────────────────────────

    public ProactiveOrchestrator(Context context, String contactId, DeepSeekClient llmClient) {
        this.contactId = contactId;
        this.llmClient = llmClient;
        this.decisionClient = new TriggerDecisionClient(llmClient);
        this.lifeEngine = new LifeEngine(context);
        this.emotionEngine = new EmotionEngine(context);
        this.emotionEngine.setLlmClient(llmClient);
        this.personaManager = new PersonaStateManager(context);
        this.chatRepo = new ChatRepository(context);

        // Load persisted state
        this.lifeEngine.load(contactId);
        this.emotionEngine.load(contactId);
        this.personaManager.load(contactId);

        // Scheduler that calls onTimerTick
        this.scheduler = new TriggerScheduler(this::onTimerTick);
    }

    /** Set the API key and default callback for timer-driven triggers. */
    public void configure(String apiKey, Callback callback) {
        this.apiKey = apiKey;
        this.defaultCallback = callback;
    }

    /**
     * Enable fast test mode: 1-minute idle threshold + 30-second tick interval.
     * The proactive pipeline will fire ~1 minute after the last user message.
     */
    public void enableTestMode() {
        lifeEngine.setIdleThresholdMs(60_000L);          // 1 minute idle → READY
        scheduler.setInterval(30_000L, 30_000L);          // tick every 30s
    }

    // ── lifecycle ───────────────────────────────────────────────

    public void start() {
        Log.i(TAG, "start() called for contact=" + contactId);
        scheduler.start();
    }

    public void pause() {
        Log.i(TAG, "pause() called for contact=" + contactId);
        scheduler.pause();
        persistAll();
    }

    public void resume() {
        Log.i(TAG, "resume() called for contact=" + contactId);
        scheduler.resume();
    }

    public void stop() {
        Log.i(TAG, "stop() called for contact=" + contactId);
        scheduler.stop();
        persistAll();
    }

    // ── entry point 1: post-reply evaluation ────────────────────

    /**
     * Call after the AI has replied to a user message and the reply has been
     * displayed. Feeds messages to EmotionEngine, then evaluates triggers.
     *
     * @param apiKey      DeepSeek API key
     * @param messages    current full message list (reference held for timer ticks)
     * @param userMessage the raw user input that triggered this round
     * @param callback    result callback (main thread)
     */
    public void evaluatePostReply(String apiKey, List<ChatMessage> messages,
                                   String userMessage, Callback callback) {
        Log.d(TAG, "evaluatePostReply: userMessage='" + userMessage + "'");
        this.cachedMessages = messages;

        // Feed lifecycle signal
        lifeEngine.onUserMessage(System.currentTimeMillis());
        scheduler.suggestNormal();

        // Analyse emotions from recent messages (async)
        emotionEngine.analyzeMessages(apiKey, messages, () -> {
            Log.d(TAG, "evaluatePostReply: emotion analysis complete, evaluating triggers");
            // After analysis completes, evaluate all triggers
            evaluateAllTriggers(apiKey, messages, callback);
        });
    }

    // ── entry point 2: timer tick ───────────────────────────────

    private void onTimerTick() {
        if (apiKey == null || apiKey.isEmpty()) {
            Log.w(TAG, "onTimerTick: apiKey not set, skipping");
            return;
        }

        long now = System.currentTimeMillis();
        lifeEngine.onTimerTick(now);

        LifeEngineEvent lifeEvent = lifeEngine.checkForLifeSignal(now);
        // Also check EmotionEngine — it may have a signal even if LifeEngine is quiet
        EmotionEngineEvent emotionEvent = emotionEngine.checkForEmotionalSignal();
        // Use empty list for fresh contacts with no messages yet
        List<ChatMessage> msgs = cachedMessages != null ? cachedMessages : new ArrayList<>();

        // Bail only when BOTH engines are silent
        if (lifeEvent == null && emotionEvent == null) {
            Log.v(TAG, "onTimerTick: both engines silent, stretching interval");
            scheduler.suggestStretch();
            return;
        }

        if (lifeEvent != null) {
            Log.i(TAG, "onTimerTick: LifeEngine fired — reason=" + lifeEvent.reason
                    + ", confidence=" + lifeEvent.confidence
                    + ", idleMinutes=" + lifeEvent.idleMinutes);
        }
        if (emotionEvent != null) {
            Log.i(TAG, "onTimerTick: EmotionEngine fired — reason=" + emotionEvent.reason
                    + ", urgency=" + emotionEvent.urgency);
        }

        // Feed whichever engine(s) fired into the LLM decision pipeline
        decisionClient.decide(apiKey, msgs, lifeEvent, emotionEvent,
                personaManager.current(),
                decision -> {
                    if (decision.shouldSpeak) {
                        Log.i(TAG, "onTimerTick: LLM decided to speak, topicHint="
                                + decision.topicHint + ", confidence=" + decision.confidence);
                        decisionClient.generateMessage(apiKey, decision.topicHint,
                                msgs, personaManager.current(),
                                new DeepSeekClient.Callback() {
                                    @Override
                                    public void onSuccess(String reply) {
                                        Log.i(TAG, "onTimerTick: proactive message generated successfully");
                                        personaManager.evolveMood(0.2f);
                                        personaManager.persist(contactId);
                                        persistAll();
                                        if (defaultCallback != null) {
                                            defaultCallback.onProactiveMessageReady(reply);
                                        }
                                    }

                                    @Override
                                    public void onError(String error) {
                                        Log.e(TAG, "onTimerTick: generateMessage failed: " + error);
                                        if (defaultCallback != null) {
                                            defaultCallback.onError(error);
                                        }
                                    }
                                });
                    } else {
                        Log.i(TAG, "onTimerTick: LLM decided NOT to speak, stretching interval");
                        scheduler.suggestStretch();
                    }
                });
    }

    // ── internal pipeline ───────────────────────────────────────

    private void evaluateAllTriggers(String apiKey, List<ChatMessage> messages,
                                      Callback callback) {
        long now = System.currentTimeMillis();

        LifeEngineEvent lifeEvent = lifeEngine.checkForLifeSignal(now);
        EmotionEngineEvent emotionEvent = emotionEngine.checkForEmotionalSignal();

        if (lifeEvent == null && emotionEvent == null) {
            Log.v(TAG, "evaluateAllTriggers: both engines silent, no action");
            scheduler.suggestStretch();
            callback.onNoAction();
            return;
        }

        if (lifeEvent != null) {
            Log.i(TAG, "evaluateAllTriggers: LifeEngine — reason=" + lifeEvent.reason);
        }
        if (emotionEvent != null) {
            Log.i(TAG, "evaluateAllTriggers: EmotionEngine — reason=" + emotionEvent.reason);
        }

        decisionClient.decide(apiKey, messages, lifeEvent, emotionEvent,
                personaManager.current(),
                decision -> {
                    if (!decision.shouldSpeak) {
                        Log.i(TAG, "evaluateAllTriggers: LLM decided NOT to speak");
                        callback.onNoAction();
                        return;
                    }

                    Log.i(TAG, "evaluateAllTriggers: LLM decided to speak, generating message");
                    // Generate the actual proactive message
                    decisionClient.generateMessage(apiKey, decision.topicHint,
                            messages, personaManager.current(),
                            new DeepSeekClient.Callback() {
                                @Override
                                public void onSuccess(String reply) {
                                    Log.i(TAG, "evaluateAllTriggers: proactive message generated");
                                    // Evolve persona state based on proactive interaction
                                    personaManager.evolveEnergy(false, 0);
                                    if (emotionEvent != null) {
                                        personaManager.evolveMood(emotionEvent.snapshot.valence);
                                        personaManager.evolveEmotionalResonance(
                                                emotionEvent.snapshot.valence);
                                    }
                                    personaManager.persist(contactId);
                                    persistAll();
                                    callback.onProactiveMessageReady(reply);
                                }

                                @Override
                                public void onError(String error) {
                                    Log.e(TAG, "evaluateAllTriggers: generateMessage failed: " + error);
                                    callback.onError(error);
                                }
                            });
                });
    }

    // ── persistence ─────────────────────────────────────────────

    private void persistAll() {
        lifeEngine.persist(contactId);
        emotionEngine.persist(contactId);
        personaManager.persist(contactId);
    }

    // ── accessors ───────────────────────────────────────────────

    public ChatRepository getChatRepo() {
        return chatRepo;
    }

    public PersonaStateManager getPersonaManager() {
        return personaManager;
    }

    public LifeEngine getLifeEngine() {
        return lifeEngine;
    }

    public EmotionEngine getEmotionEngine() {
        return emotionEngine;
    }

    public TriggerScheduler getScheduler() {
        return scheduler;
    }
}
