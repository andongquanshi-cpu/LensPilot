package com.river.acewireless.analysis

import android.os.SystemClock
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel

enum class FilterKind { NONE, POLARIZER, CLOSE_UP, BLACK_MIST, STAR }
/** JPEG of the complete displayed camera picture, without app UI, borders or synthetic filters.
 * sampledAtMs is phone monotonic PixelCopy request time, NOT camera exposure time.
 */
data class SceneImage(val jpeg: ByteArray, val width: Int, val height: Int,
    val sampledAtMs: Long, val sequence: Long, val installedFilter: FilterKind? = null, val renderSerial: Long = 0)
data class FilterAdvice(val recommendation: FilterKind, val reason: String,
    val visibleEvidence: List<String>, val uncertainty: String, val userAction: String)

/** Implement on a backend/model adapter. Bind networking to CameraSession.internetNetwork(),
 * not the process default camera Wi-Fi. Never embed model API keys in the APK.
 */
fun interface SceneAnalyzer { suspend fun analyze(image: SceneImage): FilterAdvice }

/** One in-flight request, one newest pending image; no unbounded upload queue. */
class SceneAnalysisPipeline(private val scope: CoroutineScope,
    private val result: (SceneImage, FilterAdvice) -> Unit,
    private val failure: (String) -> Unit,
    private val clockMs: () -> Long = SystemClock::elapsedRealtime) {
    private var queue: Channel<SceneImage>? = null
    private var job: Job? = null
    fun start(analyzer: SceneAnalyzer) {
        check(job == null) { "先停止上一次分析" }
        val channel = Channel<SceneImage>(Channel.CONFLATED); queue = channel
        job = scope.launch {
            for (image in channel) {
                if (clockMs()-image.sampledAtMs > 2500) continue
                try {
                    val advice = withTimeout(8_000) { withContext(Dispatchers.IO) { analyzer.analyze(image) } }
                    if (clockMs()-image.sampledAtMs <= 8_000) result(image,advice)
                } catch (e: TimeoutCancellationException) { failure("场景分析超时，跳过旧画面") }
                catch (e: CancellationException) { throw e }
                catch (e: Exception) { failure("场景分析失败：${e.message}") }
            }
        }
    }
    fun offer(image: SceneImage) { queue?.trySend(image) }
    suspend fun stop() { queue?.close(); job?.cancelAndJoin(); queue=null;job=null }
}
