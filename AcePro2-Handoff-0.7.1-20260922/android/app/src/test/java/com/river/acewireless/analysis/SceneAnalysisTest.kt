package com.river.acewireless.analysis

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class SceneAnalysisTest {
    private fun frame(id: Long) = SceneImage(byteArrayOf(1),1,1,1000,id)
    private fun advice() = FilterAdvice(FilterKind.NONE,"证据不足",emptyList(),"距离未知","保持原镜头")
    @Test fun slowAnalysisKeepsOnlyNewestPendingFrame() = runBlocking {
        val firstStarted=CompletableDeferred<Unit>()
        val release=CompletableDeferred<Unit>()
        val lastDelivered=CompletableDeferred<Unit>()
        val observed=mutableListOf<Long>()
        val pipeline=SceneAnalysisPipeline(this,{ image,_ -> if(image.sequence==3L) lastDelivered.complete(Unit) },{ error(it) },{1000L})
        pipeline.start { image ->
            synchronized(observed) { observed.add(image.sequence) }
            if(image.sequence==1L) { firstStarted.complete(Unit);release.await() }
            advice()
        }
        pipeline.offer(frame(1))
        withTimeout(3000) { firstStarted.await() }
        pipeline.offer(frame(2));pipeline.offer(frame(3));release.complete(Unit)
        withTimeout(3000) { lastDelivered.await() }
        pipeline.stop()
        assertEquals(listOf(1L,3L),observed)
    }
    @Test fun stoppingCancelsInFlightAnalysisWithoutPublishingResult() = runBlocking {
        val started=CompletableDeferred<Unit>();val canceled=CompletableDeferred<Unit>()
        var count=0
        val pipeline=SceneAnalysisPipeline(this,{ _,_ -> count++ },{ error(it) },{1000L})
        pipeline.start {
            try { started.complete(Unit);awaitCancellation() }
            finally { canceled.complete(Unit) }
        }
        pipeline.offer(frame(1))
        withTimeout(3000) { started.await() }
        pipeline.stop()
        assertTrue(canceled.isCompleted)
        assertEquals(0,count)
    }
}
