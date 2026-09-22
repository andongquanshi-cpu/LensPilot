package com.river.acewireless.analysis

import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.PixelCopy
import android.view.SurfaceView
import kotlinx.coroutines.*
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicLong
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.math.roundToInt

/** Sampling and JPEG encoding are separate from the compressed video/decoder queue. */
class SceneSampler(private val surface: SurfaceView, private val scope: CoroutineScope,
    private val frame: (SceneImage) -> Unit, private val status: (String) -> Unit) {
    private val renderedAt = AtomicLong(0)
    private val renderSerial = AtomicLong(0)
    private var job: Job? = null
    private var sequence = 0L
    var latest: SceneImage? = null; private set
    var installedFilter: FilterKind? = null
    val running get() = job?.isActive == true
    fun onRendered(atMs: Long) { renderedAt.set(atMs); renderSerial.incrementAndGet() }
    fun renderSequence(): Long = renderSerial.get()
    fun invalidate() { renderedAt.set(0); latest=null }
    fun start() {
        if (job?.isCompleted == false) return
        job=scope.launch(Dispatchers.Main) {
            while (isActive) {
                val started = SystemClock.elapsedRealtime()
                if (renderedAt.get() == 0L || started-renderedAt.get() > 1000 || !surface.holder.surface.isValid || surface.width <= 0 || surface.height <= 0) {
                    status("等待新鲜画面，未上传")
                    delay(1000);continue
                }
                try {
                    val image=captureFresh(renderSerial.get()-1)
                    latest=image;frame(image)
                    status("AI取帧 ${image.width}×${image.height} · ${image.jpeg.size/1024} KB · 仅本地，未接模型")
                } catch(e: CancellationException) { throw e }
                catch(e: Exception) { status("抽帧暂不可用：${e.message}") }
                delay((1000-(SystemClock.elapsedRealtime()-started)).coerceAtLeast(1))
            }
        }
    }
    /** Wait for a newly rendered frame, rather than returning a cached pre-trigger screenshot. */
    suspend fun captureFresh(afterSerial: Long): SceneImage = withContext(Dispatchers.Main) {
        withTimeout(2500) {
            while (renderSerial.get() <= afterSerial || renderedAt.get()==0L ||
                SystemClock.elapsedRealtime()-renderedAt.get() > 1000 ||
                !surface.holder.surface.isValid || surface.width<=0 || surface.height<=0) delay(10)
            val serial=renderSerial.get()
            val started=SystemClock.elapsedRealtime()
            val scale=minOf(1.0,1280.0/maxOf(surface.width,surface.height))
            val w=(surface.width*scale).roundToInt().coerceAtLeast(1)
            val h=(surface.height*scale).roundToInt().coerceAtLeast(1)
            val bitmap=copy(w,h)
            val jpeg=try {
                withContext(Dispatchers.Default) {
                    ByteArrayOutputStream().use { out ->
                        check(bitmap.compress(Bitmap.CompressFormat.JPEG,90,out));out.toByteArray()
                    }
                }
            } finally { bitmap.recycle() }
            SceneImage(jpeg,w,h,started,++sequence,installedFilter,serial)
        }
    }
    private suspend fun copy(w: Int,h: Int): Bitmap = suspendCancellableCoroutine { continuation ->
        val bitmap=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888)
        try {
            PixelCopy.request(surface,bitmap,{ code ->
                if (!continuation.isActive) bitmap.recycle()
                else if (code==PixelCopy.SUCCESS) continuation.resume(bitmap) { _,value,_ -> value.recycle() }
                else { bitmap.recycle();continuation.resumeWithException(IllegalStateException("PixelCopy $code")) }
            },Handler(Looper.getMainLooper()))
        } catch(e: Exception) { bitmap.recycle();if(continuation.isActive) continuation.resumeWithException(e) }
    }
    fun stop() { job?.cancel(); invalidate() }
}
