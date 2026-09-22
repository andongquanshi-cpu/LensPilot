package com.river.acewireless.analysis

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class SceneBatchTest {
    private fun image(serial: Long, time: Long=100) = SceneImage(byteArrayOf(1),4,3,time,serial,renderSerial=serial)
    @Test fun collectsOrderedCompleteBatch() = runBlocking {
        val batch=BurstCollector().collect(BurstConfig(3,100),TriggerSource.APP_TEST,100,5,{ image(it+1) })
        assertEquals(listOf(6L,7L,8L),batch.frames.map { it.renderSerial })
        assertEquals(3,batch.frames.size)
    }
    @Test fun rejectsRepeatedRender() = runBlocking {
        try { BurstCollector().collect(BurstConfig(1,100),TriggerSource.APP_TEST,100,5,{ image(it) });fail("duplicate accepted") }
        catch(expected: IllegalArgumentException) { }
    }
    @Test fun rejectsPreTriggerSampling() = runBlocking {
        try { BurstCollector().collect(BurstConfig(1,100),TriggerSource.APP_TEST,100,5,{ image(it+1,99) });fail("stale accepted") }
        catch(expected: IllegalArgumentException) { }
    }
    @Test fun neverReturnsPartialBatch() = runBlocking {
        var calls=0
        try {
            BurstCollector().collect(BurstConfig(3,100),TriggerSource.APP_TEST,100,5,{
                calls++;if(calls==2) error("stream stopped");image(it+1)
            });fail("partial returned")
        } catch(expected: IllegalStateException) { assertEquals(2,calls) }
    }
}
