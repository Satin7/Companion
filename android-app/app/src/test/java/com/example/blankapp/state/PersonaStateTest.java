package com.example.blankapp.state;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class PersonaStateTest {

    @Test
    public void defaultValues() {
        PersonaState s = new PersonaState();
        assertEquals(0.7f, s.getEnergy(), 0.01);
        assertEquals(0.7f, s.getMood(), 0.01);
        assertEquals(3, s.getCuriosity());
        assertEquals(3, s.getCare());
        assertEquals(3, s.getSharing());
        assertEquals(3, s.getMemory());
        assertFalse(s.isBusy());
    }

    @Test
    public void motivationSumsAllFour() {
        PersonaState s = new PersonaState();
        assertEquals(12, s.getMotivation()); // 3+3+3+3
    }

    @Test
    public void isReceptive() {
        PersonaState s = new PersonaState();
        assertTrue(s.isReceptive());

        s.setEnergy(0.3f);
        s.setMood(0.2f);
        assertFalse(s.isReceptive());
    }

    @Test
    public void jsonRoundtrip() {
        PersonaState original = new PersonaState();
        original.setEnergy(0.5f);
        original.setMood(0.8f);
        original.setCuriosity(4);
        original.setCare(2);
        original.setOpenness(0.3f);

        String json = original.toJson().toString();
        PersonaState restored = PersonaState.fromJson(json);

        assertEquals(original.getEnergy(), restored.getEnergy(), 0.01);
        assertEquals(original.getMood(), restored.getMood(), 0.01);
        assertEquals(original.getCuriosity(), restored.getCuriosity());
        assertEquals(original.getCare(), restored.getCare());
        assertEquals(original.getOpenness(), restored.getOpenness(), 0.01);
    }

    @Test
    public void copyCreatesIndependentClone() {
        PersonaState original = new PersonaState();
        original.setEnergy(0.9f);
        PersonaState copy = original.copy();

        assertEquals(original.getEnergy(), copy.getEnergy(), 0.01);
        copy.setEnergy(0.1f);
        assertEquals(0.9f, original.getEnergy(), 0.01); // original unchanged
    }

    @Test
    public void clampValues() {
        PersonaState s = new PersonaState();
        s.setEnergy(2.0f);
        assertEquals(1.0f, s.getEnergy(), 0.01);

        s.setEnergy(-1.0f);
        assertEquals(0.0f, s.getEnergy(), 0.01);

        s.setCuriosity(10);
        assertEquals(5, s.getCuriosity());

        s.setCuriosity(0);
        assertEquals(1, s.getCuriosity());
    }
}
