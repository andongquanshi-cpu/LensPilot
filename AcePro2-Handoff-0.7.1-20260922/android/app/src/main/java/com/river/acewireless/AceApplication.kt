package com.river.acewireless
import android.app.Application
import com.arashivision.sdk.camera.InstaCameraSDK
class AceApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        InstaCameraSDK.init(this) { fileDir = filesDir.absolutePath; cacheDir = this@AceApplication.cacheDir.absolutePath }
    }
}
