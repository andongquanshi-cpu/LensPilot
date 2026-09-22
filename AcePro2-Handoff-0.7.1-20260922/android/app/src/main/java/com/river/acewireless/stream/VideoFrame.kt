package com.river.acewireless.stream

import java.io.ByteArrayOutputStream

/** One complete Annex-B access unit. ptsUs is camera-relative, not wall-clock time.
 * Consumers own the payload but must not mutate it. codecConfig contains SPS/PPS (+ VPS for HEVC).
 */
data class VideoFrame(val data: ByteArray, val ptsUs: Long, val mime: String,
    val width: Int, val height: Int, val keyFrame: Boolean, val codecConfig: List<ByteArray>)

/** SDK fragments with equal timestamps belong to one access unit, flushed at the next timestamp.
 * The incomplete tail is deliberately discarded on stop / discontinuity.
 */
class FrameAssembler(private val emit: (ByteArray, Long) -> Unit) {
    private val bytes = ByteArrayOutputStream()
    private var timestamp: Long? = null
    fun reset() { timestamp = null; bytes.reset() }
    fun append(data: ByteArray, ts: Long) {
        if (timestamp != null && ts < timestamp!!) reset()
        if (timestamp != null && timestamp != ts) { emit(bytes.toByteArray(), timestamp!!); bytes.reset() }
        timestamp = ts
        require(bytes.size() + data.size <= 4 * 1024 * 1024) { "视频帧超过 4 MB" }
        bytes.write(data)
    }
}

object NalUnits {
    private val prefix = byteArrayOf(0, 0, 0, 1)
    /** Accept Annex B, four-byte length-prefixed data, or a single raw NAL. */
    fun split(data: ByteArray): List<ByteArray> {
        val marks = mutableListOf<Pair<Int,Int>>()
        var i = 0
        while (i + 2 < data.size) {
            val n = if (data[i] == 0.toByte() && data[i+1] == 0.toByte()) {
                if (data[i+2] == 1.toByte()) 3
                else if (i+3 < data.size && data[i+2] == 0.toByte() && data[i+3] == 1.toByte()) 4 else 0
            } else 0
            if (n > 0) { marks.add(i to n); i += n } else i++
        }
        if (marks.isNotEmpty() && marks.first().first == 0) return marks.mapIndexedNotNull { index, (start, n) ->
            val end = marks.getOrNull(index+1)?.first ?: data.size
            if (end > start+n) data.copyOfRange(start+n, end) else null
        }
        val lengths = mutableListOf<ByteArray>(); i = 0
        while (i+4 <= data.size) {
            val n = ((data[i].toInt() and 255) shl 24) or ((data[i+1].toInt() and 255) shl 16) or
                ((data[i+2].toInt() and 255) shl 8) or (data[i+3].toInt() and 255)
            if (n <= 0 || n > data.size-i-4) break
            lengths.add(data.copyOfRange(i+4,i+4+n)); i += 4+n
        }
        if (i == data.size && lengths.isNotEmpty()) return lengths
        return if (data.isEmpty()) emptyList() else listOf(data)
    }
    fun annex(nals: List<ByteArray>): ByteArray = ByteArrayOutputStream().apply {
        nals.forEach { write(prefix); write(it) }
    }.toByteArray()
    fun type(nal: ByteArray, mime: String) = if (mime == "video/hevc") (nal[0].toInt() and 126) shr 1 else nal[0].toInt() and 31
}

class FrameEncoderInfo(var mime: String) {
    private val config = sortedMapOf<Int,ByteArray>()
    fun make(data: ByteArray, tsMs: Long, width: Int, height: Int): VideoFrame {
        val nals = NalUnits.split(data)
        // Parameter sets are unambiguous evidence if a firmware reports the wrong codec.
        if (nals.any { it.size > 2 && (it[0].toInt() and 126) shr 1 == 32 && it[1] == 1.toByte() }) {
            if (mime != "video/hevc") { mime = "video/hevc"; config.clear() }
        }
        val required = if (mime == "video/hevc") listOf(32,33,34) else listOf(7,8)
        nals.forEach { val t = NalUnits.type(it,mime); if (t in required) config[t] = it.copyOf() }
        val key = nals.any { val t = NalUnits.type(it,mime); if (mime == "video/hevc") t in 16..21 else t == 5 }
        return VideoFrame(NalUnits.annex(nals),tsMs * 1000L,mime,width,height,key,
            if (required.all { config.containsKey(it) }) required.map { NalUnits.annex(listOf(config.getValue(it))) } else emptyList())
    }
}
