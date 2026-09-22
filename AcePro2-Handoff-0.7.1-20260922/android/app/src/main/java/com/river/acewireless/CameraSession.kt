package com.river.acewireless

import android.app.Application
import android.net.*
import android.os.SystemClock
import android.util.Log
import android.view.Surface
import com.arashivision.sdk.camera.api.CameraDevice
import com.arashivision.sdk.camera.api.param.listener.DisconnectListener
import com.arashivision.sdk.camera.api.param.listener.CaptureStatusListener
import com.arashivision.sdk.camera.core.model.FunctionMode
import com.arashivision.sdk.camera.core.model.capture.CameraCaptureStatus
import com.arashivision.sdk.camera.api.preview.*
import com.arashivision.sdk.camera.core.model.ConnectType
import com.arashivision.sdk.camera.core.model.option.VideoEncode
import com.river.acewireless.stream.*
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

class CameraSession(private val app: Application, private val scope: CoroutineScope,
    private val status: (String) -> Unit, private val stats: (String) -> Unit, private val videoAspect: (Double) -> Unit, private val frameRendered: (Long) -> Unit = {}) {
    private val cm = app.getSystemService(ConnectivityManager::class.java)
    private var task: Job? = null
    private var device: CameraDevice? = null
    @Volatile private var active = false
    private var monitorOnly = false
    val monitoring get() = monitorOnly && task?.isCompleted == false
    @Volatile private var width = 1280
    @Volatile private var height = 960
    private val lastKeyRequest = AtomicLong(0)
    val forwarding = ForwardingBranch(scope, ::requestKeyFrame, ::report)
    private fun report(s: String) { Log.i("AceWireless",s); status(s) }
    private fun requestKeyFrame() {
        val now = SystemClock.elapsedRealtime(); val last = lastKeyRequest.get()
        if (now-last > 1_000 && lastKeyRequest.compareAndSet(last,now)) {
            scope.launch(Dispatchers.Main) { runCatching { device?.preview?.requestStreamIframe() } }
        }
    }
    /** Forwarding uses a separately selected validated network, NOT process-default camera Wi-Fi. */
    fun internetNetwork(): Network? = cm.allNetworks.firstOrNull { n ->
        cm.getNetworkCapabilities(n)?.let { it.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
            it.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) && !it.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) } == true
    }
    fun startForwarding(sink: VideoForwarder): Result<Unit> = runCatching {
        check(active) { "请先开启预览" }
        val internet = internetNetwork() ?: error("没有可用的蜂窝网络，请开启移动数据")
        forwarding.start(sink, internet)
    }
    suspend fun stopForwarding() = forwarding.stop()
    fun start(surface: Surface?, eventsOnly: Boolean = false) {
        if (task?.isCompleted == false) return
        val network = cm.allNetworks.firstOrNull { cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true }
        if (network == null) { report("未连接 Wi-Fi：请先在手机设置中连接 Ace Pro 2 热点"); return }
        monitorOnly = eventsOnly
        width = 1280; height = 960
        task = scope.launch(Dispatchers.Main) {
            val camera = CameraDevice.get(ConnectType.WIFI); device = camera
            data class Packet(val frame: PreviewStreamFrame, val arrivedMs: Long)
            val packets = Channel<Packet>(64)
            val queueAge = AtomicLong(0)
            val skipped = AtomicLong(0); val resets = AtomicLong(0)
            val lost = AtomicBoolean(false)
            val fragments = AtomicLong(0); val bytes = AtomicLong(0); val frames = AtomicLong(0)
            val rendered = AtomicLong(0); val dropped = AtomicLong(0)
            val receivedAt = AtomicLong(SystemClock.elapsedRealtime())
            var worker: Job? = null; var ticker: Job? = null
            var selectedType: PreviewStreamType? = null
            var previewInitialized=false
            var captureRegistered=false
            val eventNumber=AtomicLong(0)
            val listeningSince=SystemClock.elapsedRealtime()
            val eventLog=java.io.File(app.filesDir,"capture-events.log")
            if(eventsOnly) eventLog.writeText("Diagnostic session ${System.currentTimeMillis()}\nInitial callbacks may be state synchronization, not key presses.\n")
            fun captureEvent(name: String, mode: FunctionMode, detail: String = "") {
                val event="事件 #${eventNumber.incrementAndGet()} +${SystemClock.elapsedRealtime()-listeningSince}ms $name · $mode $detail"
                Log.i("AceCaptureEvent",event)
                synchronized(eventLog) {
                    runCatching {
                        if(eventLog.length()>1_048_576) eventLog.writeText("Log truncated\n")
                        eventLog.appendText(event+"\n")
                    }
                }
                status(event)
            }
            val captureListener=object : CaptureStatusListener {
                override fun onCaptureStarting(mode: FunctionMode) = captureEvent("STARTING",mode)
                override fun onCaptureWorking(mode: FunctionMode) = captureEvent("WORKING",mode)
                override fun onCaptureStopping(mode: FunctionMode) = captureEvent("STOPPING",mode)
                override fun onCaptureFinish(mode: FunctionMode, files: List<String>) = captureEvent("FINISH",mode,"files=${files.size}")
                override fun onCaptureError(mode: FunctionMode, error: Throwable) = captureEvent("ERROR",mode,error.message.orEmpty())
                override fun onCaptureTimeChanged(mode: FunctionMode, time: Long) = captureEvent("CAPTURE_TIME",mode,"value=$time（非按键时长）")
                override fun onCaptureCountChanged(mode: FunctionMode, count: Int) = captureEvent("COUNT",mode,"value=$count")
                override fun onCaptureSubStatusChanged(mode: FunctionMode, subStatus: CameraCaptureStatus.SubStatus) = captureEvent("SUBSTATUS",mode,subStatus.toString())
            }
            val disconnected = CompletableDeferred<Unit>()
            val disconnectListener = object : DisconnectListener {
                override fun onDisconnect(throwable: Throwable?) {
                    report("相机连接已断开" + (throwable?.message?.let { "：$it" } ?: "")); disconnected.complete(Unit)
                }
            }
            val listener = object : CameraStreamListener {
                override fun onOpening() { report("正在启动视频流…") }
                override fun onOpened() { report("视频流已开启，等待关键帧…"); requestKeyFrame() }
                override fun onIdle() { }
                override fun onParamsChanged(paramsUpdate: PreviewStreamParamsUpdate) {
                    if (paramsUpdate.previewWidth > 0 && paramsUpdate.previewHeight > 0) {
                        width = paramsUpdate.previewWidth; height = paramsUpdate.previewHeight
                    }
                    Log.i("AceWireless", "Preview size ${width}x${height}, fps=${paramsUpdate.previewFps}")
                }
                override fun onStreamDataNotify(streamData: PreviewStreamFrame) {
                    if (!active || !streamData.type.isVideo) return
                    fragments.incrementAndGet(); bytes.addAndGet(streamData.data.size.toLong())
                    receivedAt.set(SystemClock.elapsedRealtime())
                    // SDK may reuse the buffer after this callback returns.
                    val copy = streamData.copy(data = streamData.data.copyOf())
                    if (packets.trySend(Packet(copy,SystemClock.elapsedRealtime())).isFailure) { lost.set(true); dropped.incrementAndGet() }
                }
            }
            try {
                report("正在通过 Wi-Fi 连接相机…")
                check(cm.bindProcessToNetwork(network)) { "无法选择相机 Wi-Fi 网络" }
                camera.registerDisconnectListener(disconnectListener)
                if(eventsOnly) {
                    camera.capture.registerCaptureStatusListener(captureListener)
                    captureRegistered=true
                }
                withTimeout(20_000) { camera.connect(network.networkHandle).getOrThrow() }
                if(eventsOnly) {
                    val mode=withTimeoutOrNull(3_000) { camera.capture.functionMode.fetchValue().getOrNull() }
                    eventLog.appendText("Connected mode=$mode\n")
                    report("仅监听拍摄事件 · 当前模式 ${mode ?: "未知，请机身确认"}")
                    stats("不开视频流，不自动拍照、不上传。\n记录的是拍摄事件，尚不能判定长按。")
                    disconnected.await()
                    return@launch
                }
                val type = withTimeoutOrNull(3_000) { camera.system.fetchCameraType().getOrNull() }
                report("已连接 ${type ?: "相机"}，正在准备预览")
                val encode = withTimeoutOrNull(3_000) { camera.system.fetchVideoEncodeType().getOrNull() }
                val info = FrameEncoderInfo(if (encode == VideoEncode.ENCODE_H265) "video/hevc" else "video/avc")
                Log.i("AceWireless","Camera=$type codec=$encode")
                active = true
                worker = launch(Dispatchers.Default) {
                    val decoder = VideoDecoder(requireNotNull(surface), ::requestKeyFrame, videoAspect, frameRendered)
                    var first = true
                    val assembler = FrameAssembler { data, ts ->
                        val frame = info.make(data,ts,width,height)
                        frames.incrementAndGet()
                        forwarding.offer(frame)
                        decoder.offer(frame)
                        rendered.set(decoder.rendered.get())
                        if (first && decoder.rendered.get() > 0) { first = false; report("实时画面已显示") }
                    }
                    try {
                        while (isActive) {
                            // Drain output even if Wi-Fi temporarily stops delivering input.
                            try { decoder.pump() } catch (e: Exception) {
                                Log.w("AceWireless","Output recovery",e)
                                assembler.reset(); decoder.reset(); forwarding.discontinuity(); requestKeyFrame()
                            }
                            rendered.set(decoder.rendered.get()); skipped.set(decoder.skipped); resets.set(decoder.resets)
                            val received = withTimeoutOrNull(8) { packets.receiveCatching() } ?: continue
                            val queued = received.getOrNull() ?: break
                            val age = SystemClock.elapsedRealtime()-queued.arrivedMs
                            queueAge.set(age)
                            if (lost.getAndSet(false) || age > 250) {
                                dropped.incrementAndGet()
                                while (packets.tryReceive().isSuccess) { }
                                assembler.reset(); decoder.reset(); forwarding.discontinuity(); requestKeyFrame()
                                continue
                            }
                            val packet = queued.frame
                            // Ace is a single-lens camera. Never mix VIDEO/L/R fragments in one decoder.
                            if (selectedType == null) selectedType = packet.type
                            if (packet.type != selectedType) continue
                            try { assembler.append(packet.data,packet.timestamp) }
                            catch (e: Exception) {
                                Log.e("AceWireless","Decode error",e)
                                assembler.reset(); decoder.reset(); forwarding.discontinuity(); requestKeyFrame()
                                report("正在恢复视频解码：${e.message}")
                            }
                        }
                    } finally { decoder.close() }
                }
                ticker = launch {
                    var oldFrames = 0L; var oldRendered = 0L; var oldBytes = 0L; var tick = SystemClock.elapsedRealtime()
                    while (isActive) {
                        delay(1_000)
                        val now = SystemClock.elapsedRealtime(); val seconds = (now-tick)/1000.0
                        val count = frames.get(); val total = bytes.get()
                        stats("${width} × ${height}  ·  ${info.mime.removePrefix("video/")}\n" +
                            "接收 %.1f / 显示 %.1f fps · %.2f Mbps\n".format((count-oldFrames)/seconds,(rendered.get()-oldRendered)/seconds,(total-oldBytes)*8/seconds/1_000_000) +
                            "排队 ${queueAge.get()} ms · 恢复 ${resets.get()} 次 · 跳过旧画面 ${skipped.get()}\n转发接口就绪，未配置服务器")
                        Log.i("AceWireless","STATS frames=$count render=${rendered.get()} fragments=${fragments.get()} bytes=$total queueMs=${queueAge.get()} resets=${resets.get()} skipped=${skipped.get()}")
                        if (now-receivedAt.get() > 5_000) { report("暂未收到视频，请确认相机热点和机身授权，关闭官方 App 后重试"); requestKeyFrame() }
                        oldFrames=count;oldRendered=rendered.get();oldBytes=total;tick=now
                    }
                }
                previewInitialized=true
                camera.preview.init(app)
                camera.preview.registerCameraStreamListener(listener)
                camera.preview.startStream()
                requestKeyFrame()
                disconnected.await()
            } catch (e: CancellationException) {
                if (e is TimeoutCancellationException) report("连接超时，请确认已连接相机热点，并在相机上允许连接")
                else report("预览已停止")
            } catch (e: Exception) { Log.e("AceWireless","Session failed",e);report("连接失败：${e.message}") }
            finally {
                active = false
                withContext(NonCancellable) {
                    ticker?.cancelAndJoin()
                    if(captureRegistered) runCatching { camera.capture.unregisterCaptureStatusListener(captureListener) }
                    if(previewInitialized) runCatching { camera.preview.unregisterCameraStreamListener(listener); camera.preview.stopStream() }
                    packets.close(); worker?.cancelAndJoin(); forwarding.stop()
                    camera.unregisterDisconnectListener(disconnectListener)
                    withTimeoutOrNull(3_000) { runCatching { camera.disconnect() } }
                    runCatching { camera.release() }
                    device = null
                    cm.bindProcessToNetwork(null)
                }
            }
        }
    }
    fun cameraNetwork(): Network? = cm.allNetworks.firstOrNull {
        cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
    }
    fun cameraAddresses(network: Network): List<LinkAddress> = cm.getLinkProperties(network)?.linkAddresses.orEmpty()
    suspend fun stopAndWait() { task?.cancelAndJoin() }
    fun stop() { task?.cancel() }
}
