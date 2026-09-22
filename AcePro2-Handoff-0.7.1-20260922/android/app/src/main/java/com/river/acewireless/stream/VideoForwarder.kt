package com.river.acewireless.stream

import android.net.Network
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import java.util.concurrent.atomic.AtomicBoolean

/** Implement this interface for WebSocket / custom transport. Runs on Dispatchers.IO.
 * start() receives a validated Internet network; bind all outgoing sockets/DNS to this network.
 * Use network.socketFactory (e.g. OkHttp) or network.openConnection(URL).
 * send() receives COMPLETE Annex-B access units, never SDK fragments. Use codecConfig for a new decoder.
 * stop() must release resources in finally; implementations must be cancellable and have I/O timeouts.
 */
interface VideoForwarder {
    suspend fun start(network: Network)
    suspend fun send(frame: VideoFrame)
    suspend fun stop()
}

/** An optional forwarding branch; slow consumers never block the decoder.
 * Overflow discards queued dependent frames and resumes only at a fresh keyframe + codec config.
 */
class ForwardingBranch(private val scope: CoroutineScope, private val requestKeyFrame: () -> Unit,
    private val report: (String) -> Unit) {
    @Volatile private var job: Job? = null
    @Volatile private var queue: Channel<VideoFrame>? = null
    private val awaitKey = AtomicBoolean(true)
    fun start(sink: VideoForwarder, network: Network) {
        check(job == null) { "请先停止上一转发会话" }
        val channel = Channel<VideoFrame>(8); queue = channel; awaitKey.set(true)
        job = scope.launch(Dispatchers.IO) {
            try {
                withTimeout(10_000) { sink.start(network) }
                requestKeyFrame()
                for (frame in channel) withTimeout(5_000) { sink.send(frame) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { report("转发失败：${e.message}") }
            finally {
                channel.close()
                withContext(NonCancellable) { withTimeoutOrNull(3_000) { sink.stop() } }
            }
        }
    }
    fun offer(frame: VideoFrame) {
        if (job?.isActive != true) return
        val channel = queue ?: return
        if (awaitKey.get()) {
            if (!frame.keyFrame || frame.codecConfig.isEmpty()) return
            awaitKey.set(false)
        }
        if (channel.trySend(frame).isFailure) {
            while (channel.tryReceive().isSuccess) { }
            awaitKey.set(true); requestKeyFrame()
        }
    }
    fun discontinuity() { queue?.let { while (it.tryReceive().isSuccess) { } }; awaitKey.set(true) }
    suspend fun stop() { queue?.close(); job?.cancelAndJoin(); queue = null; job = null; awaitKey.set(true) }
}
