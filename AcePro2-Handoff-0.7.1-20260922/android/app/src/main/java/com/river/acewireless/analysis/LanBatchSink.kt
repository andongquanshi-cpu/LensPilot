package com.river.acewireless.analysis

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlin.coroutines.coroutineContext
import java.security.MessageDigest
import java.util.Locale
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** Camera-subnet peers use the camera Network; hotspot peers use system local routes after session cleanup. */
class LanBatchSink(private val endpoint: String, private val network: android.net.Network, private val cameraAddresses: List<android.net.LinkAddress>, private val progress: (Int,Int) -> Unit = { _,_ -> }) : AgentBatchSink {
    override suspend fun submit(batch: SceneBatch): String = withContext(Dispatchers.IO) {
        val url=URL(endpoint)
        require(url.protocol in listOf("http","https")) { "请填写 http://电脑IP:8765/batch" }
        val bytes=ByteArrayOutputStream()
        ZipOutputStream(bytes).use { zip ->
            val frames=JSONArray()
            batch.frames.forEachIndexed { index,image ->
                val name="frame-%02d.jpg".format(Locale.US,index+1)
                zip.putNextEntry(ZipEntry(name));zip.write(image.jpeg);zip.closeEntry()
                frames.put(JSONObject().put("file",name).put("width",image.width).put("height",image.height)
                    .put("sampledAtMs",image.sampledAtMs).put("renderSerial",image.renderSerial)
                    .put("installedFilter",image.installedFilter?.name ?: JSONObject.NULL))
            }
            val metadata=JSONObject().put("requestId",batch.requestId).put("source",batch.source.name)
                .put("triggeredAtMs",batch.triggeredAtMs).put("intervalMs",batch.config.intervalMs).put("frames",frames)
            zip.putNextEntry(ZipEntry("manifest.json"));zip.write(metadata.toString().toByteArray(Charsets.UTF_8));zip.closeEntry()
        }
        val payload=bytes.toByteArray()
        android.util.Log.i("AceBatch", "Uploading ${payload.size} bytes to $endpoint")
        val digest=MessageDigest.getInstance("SHA-256").digest(payload).joinToString("") { "%02x".format(it) }
        require(url.query==null && url.ref==null) { "接收地址不要带查询参数" }
        var offset=0
        var failures=0
        while(true) {
            coroutineContext.ensureActive()
            val commit=offset==payload.size
            val end=if(commit) offset else minOf(offset+8192,payload.size)
            val request=URL("$endpoint?upload=${batch.requestId}&total=${payload.size}&sha256=$digest&offset=$offset&commit=${if(commit) 1 else 0}")
            try {
                val reply=exchange(request,payload,offset,end-offset)
                val next=reply.getInt("nextOffset")
                require(next in 0..payload.size) { "电脑返回了无效进度" }
                if(reply.optBoolean("completed")) {
                    check(next==payload.size) { "接收端尚未收齐" }
                    return@withContext "电脑已接收 ${batch.frames.size} 张，整组校验通过"
                }
                if(next==offset) error("电脑接收进度未前进")
                offset=next;failures=0;progress(offset,payload.size)
            } catch(e: java.io.IOException) {
                failures++
                android.util.Log.w("AceBatch","Chunk offset=$offset retry=$failures",e)
                if(failures>=4) throw e
                delay(300L*failures)
            }
        }
        @Suppress("UNREACHABLE_CODE") ""
    }

    private fun exchange(url: URL, payload: ByteArray, offset: Int, length: Int): JSONObject {
        val destination=java.net.InetAddress.getByName(url.host)
        val onCameraSubnet=cameraAddresses.any { sameSubnet(destination.address,it.address.address,it.prefixLength) }
        val connection=(if(onCameraSubnet) network.openConnection(url) else url.openConnection()) as HttpURLConnection
        val watchdog=java.util.Timer(true)
        watchdog.schedule(object : java.util.TimerTask() {
            override fun run() { connection.disconnect() }
        },10_000)
        var consumed=false
        try {
            connection.connectTimeout=3000;connection.readTimeout=5000
            connection.instanceFollowRedirects=false;connection.requestMethod="POST";connection.doOutput=true
            connection.setRequestProperty("Content-Type","application/octet-stream")
            connection.setFixedLengthStreamingMode(length)
            connection.outputStream.use { it.write(payload,offset,length) }
            val code=connection.responseCode
            val stream=if(code in 200..299) connection.inputStream else connection.errorStream
            val response=stream?.bufferedReader()?.use { reader ->
                val text=StringBuilder();val buffer=CharArray(512)
                while(true) {
                    val count=reader.read(buffer)
                    if(count<0) break
                    check(text.length+count<=4096) { "接收端响应过大" }
                    text.append(buffer,0,count)
                }
                text.toString()
            } ?: ""
            consumed=true
            if(code==409) return JSONObject(response)
            if(code==408 || code>=500) throw java.io.IOException("电脑返回 HTTP $code: $response")
            check(code in 200..299) { "电脑返回 HTTP $code: $response；请确认接收程序已更新" }
            return JSONObject(response)
        } finally { watchdog.cancel();if(!consumed) connection.disconnect() }
    }
}

internal fun sameSubnet(target: ByteArray, local: ByteArray, prefix: Int): Boolean {
    if(target.size!=local.size || prefix !in 0..target.size*8) return false
    for(bit in 0 until prefix) {
        val mask=1 shl (7-bit%8)
        if((target[bit/8].toInt() and mask)!=(local[bit/8].toInt() and mask)) return false
    }
    return true
}
