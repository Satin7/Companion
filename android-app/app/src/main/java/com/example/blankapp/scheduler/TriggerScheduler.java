package com.example.blankapp.scheduler;

import android.os.Handler;
import android.os.Looper;

/**
 * Manages periodic trigger evaluation using Handler.postDelayed.
 *
 * Adaptive interval:
 * - Default: 2 minutes
 * - Stretch to 5 minutes when engines are quiet
 *
 * Lifecycle-aware: start/pause/resume controlled by Activity lifecycle.
 */
public class TriggerScheduler {

    private long normalIntervalMs = 2 * 60 * 1000L;   // default 2 min
    private long stretchIntervalMs = 5 * 60 * 1000L;  // default 5 min

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable tickRunnable;
    private boolean running;
    private boolean paused;
    private long currentInterval;

    public TriggerScheduler(Runnable onTick) {
        this.currentInterval = normalIntervalMs;
        this.tickRunnable = new Runnable() {
            @Override
            public void run() {
                if (!running || paused) return;
                onTick.run();
                scheduleNext();
            }
        };
    }

    /** Override both normal and stretch intervals. */
    public void setInterval(long normalMs, long stretchMs) {
        this.normalIntervalMs = normalMs;
        this.stretchIntervalMs = stretchMs;
        this.currentInterval = normalMs;
    }

    public void start() {
        if (running) return;
        running = true;
        paused = false;
        currentInterval = normalIntervalMs;
        scheduleNext();
    }

    public void pause() {
        paused = true;
        handler.removeCallbacks(tickRunnable);
    }

    public void resume() {
        if (!running || !paused) return;
        paused = false;
        scheduleNext();
    }

    public void stop() {
        running = false;
        paused = false;
        handler.removeCallbacks(tickRunnable);
    }

    /** Call when engines are quiet to stretch interval. */
    public void suggestStretch() {
        currentInterval = stretchIntervalMs;
    }

    /** Reset to default interval (e.g. after user interaction). */
    public void suggestNormal() {
        currentInterval = normalIntervalMs;
    }

    private void scheduleNext() {
        if (!running || paused) return;
        handler.postDelayed(tickRunnable, currentInterval);
    }
}
