package com.river.acewireless.stream

import android.media.MediaCodec
import android.media.MediaFormat
import android.media.MediaCodecInfo
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import java.util.concurrent.atomic.AtomicLong
import android.view.Surface
import java.nio.ByteBuffer

/** Called only by the serial stream consumer. */
class VideoDecoder(private val surface: Surface, private val requestKey: () -> Unit, private val videoAspect: (Double) -> Unit, private val onRendered: (Long) -> Unit = {}) {
    private var codec: MediaCodec? = null
    private var signature = ""
    private var waitingKey = true
    val rendered = AtomicLong(0)
    var skipped = 0L; private set
    var resets = 0L; private set
    @Volatile private var generation = 0L
    private val bufferInfo = MediaCodec.BufferInfo()
    fun reset() { close(); waitingKey = true; resets++ }
    fun offer(frame: VideoFrame) {
        if (!surface.isValid) return
        val key = "${frame.mime}:${frame.width}:${frame.height}:" + frame.codecConfig.joinToString { it.contentHashCode().toString() }
        if (codec != null && key != signature) reset()
        if (waitingKey && (!frame.keyFrame || frame.codecConfig.isEmpty())) return
        if (codec == null) {
            val format = MediaFormat.createVideoFormat(frame.mime,frame.width,frame.height)
            format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE,4*1024*1024)
            if (frame.mime == "video/hevc") format.setByteBuffer("csd-0",ByteBuffer.wrap(frame.codecConfig.fold(byteArrayOf()) { a,b -> a+b }))
            else { format.setByteBuffer("csd-0",ByteBuffer.wrap(frame.codecConfig[0])); format.setByteBuffer("csd-1",ByteBuffer.wrap(frame.codecConfig[1])) }
            val created = MediaCodec.createDecoderByType(frame.mime)
            try {
                val lowLatency = Build.VERSION.SDK_INT >= 30 && created.codecInfo.getCapabilitiesForType(frame.mime)
                    .isFeatureSupported(MediaCodecInfo.CodecCapabilities.FEATURE_LowLatency)
                if (lowLatency) format.setInteger(MediaFormat.KEY_LOW_LATENCY,1)
                format.setInteger(MediaFormat.KEY_PRIORITY,0)
                created.configure(format,surface,null,0)
                val currentGeneration = ++generation
                created.setOnFrameRenderedListener({ _, _, _ ->
                    if (generation == currentGeneration) {
                        rendered.incrementAndGet()
                        onRendered(SystemClock.elapsedRealtime())
                    }
                }, Handler(Looper.getMainLooper()))
                created.start(); codec = created; signature = key
                Log.i("AceWireless","Decoder=${created.name} lowLatency=$lowLatency")
            }
            catch (e: Exception) { created.release(); throw e }
        }
        val c = codec ?: return
        drain(c)
        var index = c.dequeueInputBuffer(0)
        val deadline = SystemClock.elapsedRealtime() + 100
        while (index < 0 && SystemClock.elapsedRealtime() < deadline) {
            drain(c)
            index = c.dequeueInputBuffer(2_000)
        }
        // A transient busy decoder is not a lost frame. Reset only after a sustained stall.
        if (index < 0) { reset(); requestKey(); return }
        val input = c.getInputBuffer(index) ?: error("无法取得解码缓冲区")
        if (input.capacity() < frame.data.size) { reset(); requestKey(); return }
        input.clear(); input.put(frame.data)
        c.queueInputBuffer(index,0,frame.data.size,frame.ptsUs,0)
        waitingKey = false
        drain(c)
    }
    fun pump() { codec?.let { drain(it) } }
    private fun drain(c: MediaCodec) {
        var latest = -1
        while (true) {
            val index = c.dequeueOutputBuffer(bufferInfo,0)
            if (index >= 0) {
                // All reference frames have been decoded. Only omit stale DISPLAY outputs.
                if (latest >= 0) { c.releaseOutputBuffer(latest,false); skipped++ }
                latest = index
            }
            else if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                val f = c.outputFormat
                fun number(key: String, fallback: Int) = if (f.containsKey(key)) f.getInteger(key) else fallback
                // Crop metadata excludes codec padding; no application crop is applied.
                val w = number("crop-right",f.getInteger(MediaFormat.KEY_WIDTH)-1) - number("crop-left",0) + 1
                val h = number("crop-bottom",f.getInteger(MediaFormat.KEY_HEIGHT)-1) - number("crop-top",0) + 1
                val sarW = number("sar-width",1).coerceAtLeast(1)
                val sarH = number("sar-height",1).coerceAtLeast(1)
                if (w > 0 && h > 0) videoAspect(w.toDouble() * sarW / (h.toDouble() * sarH))
                continue
            } else break
        }
        if (latest >= 0) c.releaseOutputBuffer(latest,true)
    }
    fun close() { generation++; codec?.let { runCatching { it.stop() }; runCatching { it.release() } }; codec = null }
}
