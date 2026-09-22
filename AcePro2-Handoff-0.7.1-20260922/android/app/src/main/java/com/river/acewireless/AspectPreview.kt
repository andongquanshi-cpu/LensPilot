package com.river.acewireless

import android.content.Context
import android.graphics.Color
import android.view.SurfaceView
import android.view.View.MeasureSpec
import android.widget.FrameLayout
import kotlin.math.roundToInt

/** Fit the complete decoded picture inside the available area, with black letterboxing. */
class AspectPreview(context: Context) : FrameLayout(context) {
    val surface = SurfaceView(context)
    private var aspect = 4.0 / 3.0
    init { setBackgroundColor(Color.BLACK); addView(surface) }
    fun setVideoAspect(value: Double) {
        if (value.isFinite() && value > 0 && aspect != value) { aspect = value; requestLayout() }
    }
    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        super.onMeasure(widthMeasureSpec,heightMeasureSpec)
        val boxWidth = measuredWidth
        val boxHeight = measuredHeight
        val w: Int; val h: Int
        if (boxWidth > boxHeight * aspect) {
            h = boxHeight; w = (h * aspect).roundToInt().coerceAtMost(boxWidth)
        } else {
            w = boxWidth; h = (w / aspect).roundToInt().coerceAtMost(boxHeight)
        }
        surface.measure(MeasureSpec.makeMeasureSpec(w,MeasureSpec.EXACTLY),MeasureSpec.makeMeasureSpec(h,MeasureSpec.EXACTLY))
    }
    override fun onLayout(changed: Boolean, left: Int, top: Int, right: Int, bottom: Int) {
        val x = (width-surface.measuredWidth)/2
        val y = (height-surface.measuredHeight)/2
        surface.layout(x,y,x+surface.measuredWidth,y+surface.measuredHeight)
    }
}
