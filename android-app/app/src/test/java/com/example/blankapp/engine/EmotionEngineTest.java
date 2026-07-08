package com.example.blankapp.engine;

import static org.junit.Assert.assertNull;

import org.junit.Before;
import org.junit.Test;

public class EmotionEngineTest {

    private EmotionEngine engine;

    @Before
    public void setUp() {
        engine = new EmotionEngine(null);
    }

    @Test
    public void initialStateIsNeutral() {
        assertNull(engine.checkForEmotionalSignal());
    }

    @Test
    public void checkForEmotionalSignal_returnsNullInNeutral() {
        assertNull(engine.checkForEmotionalSignal());
    }
}
