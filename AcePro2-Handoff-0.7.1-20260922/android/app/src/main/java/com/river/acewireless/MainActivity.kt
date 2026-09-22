package com.river.acewireless

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.os.SystemClock
import android.provider.Settings
import android.view.*
import android.widget.*
import kotlinx.coroutines.*
import com.river.acewireless.analysis.*

class MainActivity : Activity(), SurfaceHolder.Callback {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var session: CameraSession
    private lateinit var preview: SurfaceView
    private lateinit var previewBox: AspectPreview
    private lateinit var status: TextView
    private lateinit var metrics: TextView
    private lateinit var sampler: SceneSampler
    private lateinit var analysisStatus: TextView
    private var burstJob: Job? = null
    private var lastBatch: SceneBatch? = null
    private lateinit var endpointField: EditText
    private lateinit var countSelector: Spinner
    private lateinit var intervalSelector: Spinner
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setBackgroundColor(Color.rgb(15,20,28))
            val pad = (20*resources.displayMetrics.density).toInt(); setPadding(pad,pad,pad,pad)
            setOnApplyWindowInsetsListener { v, insets ->
                v.setPadding(pad,pad+insets.systemWindowInsetTop,pad,pad+insets.systemWindowInsetBottom);insets
            }
        }
        fun label(value: String, size: Float) = TextView(this).apply { text=value;textSize=size;setTextColor(Color.WHITE);setPadding(0,10,0,10) }
        root.addView(label("ACE · 无线视频",26f))
        status=label("先连接相机热点，再点开始预览",16f);root.addView(status)
        previewBox=AspectPreview(this)
        preview=previewBox.surface;preview.holder.addCallback(this)
        root.addView(previewBox,LinearLayout.LayoutParams(-1,0,1f))
        metrics=label("等待视频数据",14f);root.addView(metrics)
        fun button(title: String, action: () -> Unit) { root.addView(Button(this).apply { text=title;setOnClickListener { action() } }) }
        button("连接相机 Wi-Fi") { startActivity(Intent(Settings.ACTION_WIFI_SETTINGS)) }
        button("开始预览") {
            beginPreview()
        }
        button("监听拍摄事件（不开视频流）") {
            if(burstJob?.isCompleted==false) { analysisStatus.text="请先停止当前采集任务" }
            else scope.launch {
                session.stopAndWait();sampler.invalidate()
                session.start(null,eventsOnly=true)
            }
        }
        button("停止预览 / 监听") { burstJob?.cancel();sampler.stop();session.stop() }
        analysisStatus=label("镜片分析：偏振 / 近摄 / 黑柔 / 星光",13f);root.addView(analysisStatus)
        val selectors=LinearLayout(this).apply { orientation=LinearLayout.HORIZONTAL }
        countSelector=Spinner(this).apply {
            adapter=ArrayAdapter(this@MainActivity,android.R.layout.simple_spinner_dropdown_item,listOf("5 帧","10 帧","15 帧","20 帧"))
            setSelection(1);setBackgroundColor(Color.LTGRAY)
        }
        intervalSelector=Spinner(this).apply {
            adapter=ArrayAdapter(this@MainActivity,android.R.layout.simple_spinner_dropdown_item,listOf("间隔 100 ms","间隔 200 ms","间隔 500 ms"))
            setSelection(1);setBackgroundColor(Color.LTGRAY)
        }
        selectors.addView(countSelector,LinearLayout.LayoutParams(0,-2,1f))
        selectors.addView(intervalSelector,LinearLayout.LayoutParams(0,-2,1f));root.addView(selectors)
        endpointField=EditText(this).apply {
            hint="电脑地址：http://192.168.42.x:8765/batch"
            setTextColor(Color.WHITE);setHintTextColor(Color.LTGRAY);textSize=13f
            setSingleLine(true)
            inputType=android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_URI
            setText(getPreferences(MODE_PRIVATE).getString("agentEndpoint",""))
        }
        root.addView(endpointField)
        button("按需采集并发送（完成后停流）") { triggerBatch(TriggerSource.APP_TEST) }
        setContentView(root)
        sampler=SceneSampler(preview,scope,{}, { message -> analysisStatus.text=message })
        session=CameraSession(application,scope,
            { value -> runOnUiThread { status.text=value } },
            { value -> runOnUiThread { metrics.text=value } },
            { ratio -> runOnUiThread { previewBox.setVideoAspect(ratio) } },
            { atMs -> sampler.onRendered(atMs) })
    }
    /** Camera trigger remains disabled until a true long-press event is confirmed by the vendor. */
    private fun triggerBatch(source: TriggerSource) {
        if(session.monitoring) { analysisStatus.text="请先停止事件监听，再采集图片";return }
        if(source!=TriggerSource.APP_TEST) { analysisStatus.text="相机长按事件尚未确认，未启用";return }
        if(burstJob?.isCompleted==false) { analysisStatus.text="已有采集或提交任务，请稍候";return }
        val config=BurstConfig(listOf(5,10,15,20)[countSelector.selectedItemPosition],
            listOf(100L,200L,500L)[intervalSelector.selectedItemPosition])
        val triggeredAt=SystemClock.elapsedRealtime()
        val baseline=sampler.renderSequence()
        val endpoint=endpointField.text.toString().trim()
        getPreferences(MODE_PRIVATE).edit().putString("agentEndpoint",endpoint).apply()
        val network=session.cameraNetwork()
        if(network==null) { analysisStatus.text="请先连接相机 Wi-Fi";return }
        val sink: AgentBatchSink?=if(endpoint.isEmpty()) null else LanBatchSink(endpoint,network,session.cameraAddresses(network)) { sent,total ->
            runOnUiThread { analysisStatus.text="正在发送图片：${sent*100/total}%（$sent / $total 字节）" }
        }
        lastBatch=null
        burstJob=scope.launch {
            try {
                analysisStatus.text="正在启动短时预览，等待新画面…"
                beginPreview()
                withTimeout(35_000) { while(sampler.renderSequence()<=baseline) delay(50) }
                val batch=BurstCollector().collect(config,source,triggeredAt,baseline,sampler::captureFresh) { n,total ->
                    analysisStatus.text="正在采集 $n / $total 张原比例画面"
                }
                lastBatch=batch
                analysisStatus.text="已采集 ${batch.frames.size} 张，正在停止视频流…"
                session.stopAndWait()
                sampler.invalidate()
                metrics.text="视频流已停止，仅发送本组图片"
                android.util.Log.i("AceBatch", "Collected ${batch.frames.size} images; stream stopped")
                if(sink==null) {
                    val kb=batch.frames.sumOf { it.jpeg.size }/1024
                    analysisStatus.text="已备好 ${batch.frames.size} 张 · $kb KB · 未配置 agent，未上传"
                } else {
                    analysisStatus.text="正在提交整组画面给 agent…"
                    val reply=withTimeout(180_000) { withContext(Dispatchers.IO) { sink.submit(batch) } }
                    analysisStatus.text=reply
                }
            } catch(e: TimeoutCancellationException) { analysisStatus.text="采集或提交超时，未用旧图补齐" }
            catch(e: CancellationException) { analysisStatus.text="本次任务已取消";throw e }
            catch(e: Exception) {
                android.util.Log.e("AceBatch","Batch failed",e)
                analysisStatus.text="本次任务失败：${e.message}"
            } finally {
                withContext(NonCancellable) { session.stopAndWait() }
                sampler.invalidate()
            }
        }
    }
    private fun beginPreview() {
        if(session.monitoring) { status.text="请先停止事件监听，再开启预览";return }
        val required = mutableListOf(Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION)
        if (Build.VERSION.SDK_INT >= 33) required.add(Manifest.permission.NEARBY_WIFI_DEVICES)
        if (required.any { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }) {
            status.text="需要附近设备和精确位置权限，以便 SDK 识别相机 Wi-Fi"
            requestPermissions(required.toTypedArray(),10)
            return
        }
        sampler.invalidate()
        if(preview.holder.surface.isValid) session.start(preview.holder.surface)
        else status.text="预览窗口未就绪，请稍后重试"
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode,permissions,grantResults)
        if (requestCode == 10 && grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) beginPreview()
        else status.text="权限未完整授予，请允许附近设备及精确位置权限后重试"
    }
    override fun surfaceCreated(holder: SurfaceHolder) { }
    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) { }
    override fun surfaceDestroyed(holder: SurfaceHolder) { if (::session.isInitialized) session.stop() }
    override fun onStop() { burstJob?.cancel();if (::sampler.isInitialized) sampler.stop();if (::session.isInitialized) session.stop();super.onStop() }
    override fun onDestroy() { scope.cancel();super.onDestroy() }
}
