package com.example.blankapp.orchestration;

import android.content.Context;

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
        scheduler.start();
    }

    public void pause() {
        scheduler.pause();
        persistAll();
    }

    public void resume() {
        scheduler.resume();
    }

    public void stop() {
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
        this.cachedMessages = messages;

        // Feed lifecycle signal
        lifeEngine.onUserMessage(System.currentTimeMillis());
        scheduler.suggestNormal();

        // Analyse emotions from recent messages (async)
        emotionEngine.analyzeMessages(apiKey, messages, () -> {
            // After analysis completes, evaluate all triggers
            evaluateAllTriggers(apiKey, messages, callback);
        });
    }

    // ── entry point 2: timer tick ───────────────────────────────

    private void onTimerTick() {
        if (cachedMessages == null || cachedMessages.isEmpty()) return;
        if (apiKey == null || apiKey.isEmpty()) return;

        long now = System.currentTimeMillis();
        lifeEngine.onTimerTick(now);

        LifeEngineEvent lifeEvent = lifeEngine.checkForLifeSignal(now);
        if (lifeEvent == null) {
            scheduler.suggestStretch();
            return;
        }

        // Feed the life event into the full pipeline
        EmotionEngineEvent emotionEvent = emotionEngine.checkForEmotionalSignal();

        decisionClient.decide(apiKey, cachedMessages, lifeEvent, emotionEvent,
                personaManager.current(),
                decision -> {
                    if (decision.shouldSpeak) {
                        decisionClient.generateMessage(apiKey, decision.topicHint,
                                cachedMessages, personaManager.current(),
                                new DeepSeekClient.Callback() {
                                    @Override
                                    public void onSuccess(String reply) {
                                        personaManager.evolveMood(0.2f);
                                        personaManager.persist(contactId);
                                        persistAll();
                                        if (defaultCallback != null) {
                                            defaultCallback.onProactiveMessageReady(reply);
                                        }
                                    }

                                    @Override
                                    public void onError(String error) {
                                        if (defaultCallback != null) {
                                            defaultCallback.onError(error);
                                        }
                                    }
                                });
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
            scheduler.suggestStretch();
            callback.onNoAction();
            return;
        }

        decisionClient.decide(apiKey, messages, lifeEvent, emotionEvent,
                personaManager.current(),
                decision -> {
                    if (!decision.shouldSpeak) {
                        callback.onNoAction();
                        return;
                    }

                    // Generate the actual proactive message
                    decisionClient.generateMessage(apiKey, decision.topicHint,
                            messages, personaManager.current(),
                            new DeepSeekClient.Callback() {
                                @Override
                                public void onSuccess(String reply) {
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
