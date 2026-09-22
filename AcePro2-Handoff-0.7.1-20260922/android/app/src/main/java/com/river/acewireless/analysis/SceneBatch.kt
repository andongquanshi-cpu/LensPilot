package com.river.acewireless.analysis

import kotlinx.coroutines.*
import java.util.UUID

enum class TriggerSource { APP_TEST, CAMERA_SHUTTER_LONG_PRESS }
data class BurstConfig(val frameCount: Int = 10, val intervalMs: Long = 200) {
    init {
        require(frameCount in 1..20) { "帧数必须为 1–20" }
        require(intervalMs in 100..1000) { "间隔必须为 100–1000 ms" }
    }
}
data class SceneBatch(val requestId: String, val source: TriggerSource,
    val triggeredAtMs: Long, val config: BurstConfig, val frames: List<SceneImage>)

/** Implement with your agent's transport. All frames form ONE request, not ten independent prompts.
 * Use requestId for deduplication; explicit Internet Network routing as in SceneAnalyzer.
 */
fun interface AgentBatchSink { suspend fun submit(batch: SceneBatch): String }

/** Only successful full batches are returned; failed/duplicate/stalled images are never padded. */
class BurstCollector {
    suspend fun collect(config: BurstConfig, source: TriggerSource, triggeredAtMs: Long,
        afterSerial: Long, captureNext: suspend (Long) -> SceneImage,
        progress: (Int,Int) -> Unit = { _,_ -> }): SceneBatch =
        withTimeout(config.frameCount * (config.intervalMs + 3000) + 1000) {
            val images=ArrayList<SceneImage>(config.frameCount)
            var serial=afterSerial
            var bytes=0L
            repeat(config.frameCount) { index ->
                if(index>0) delay(config.intervalMs)
                val image=captureNext(serial)
                require(image.renderSerial>serial) { "没有新的渲染帧，取消本次采集" }
                require(image.sampledAtMs>=triggeredAtMs) { "不接受触发前的旧画面" }
                bytes+=image.jpeg.size
                require(bytes<=20L*1024*1024) { "图片批次超过 20 MB" }
                images.add(image);serial=image.renderSerial;progress(images.size,config.frameCount)
            }
            SceneBatch(UUID.randomUUID().toString(),source,triggeredAtMs,config,images.toList())
        }
}
