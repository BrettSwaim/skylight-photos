package com.twoazone.skylight.uploader

import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Server-rendered caption preview. Shows one selected photo with the caption
 * burned in and Pill/Banner/Script tabs to compare. Picking a tab sets the
 * active upload style and returns.
 */
class PreviewActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_URI = "uri"
        const val EXTRA_LOCATION = "location"
    }

    private lateinit var image: ImageView
    private lateinit var spinner: ProgressBar
    private lateinit var hint: TextView
    private var jpeg: ByteArray? = null
    private var location: String = ""
    private var current = "pill"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_preview)
        title = getString(R.string.preview_title)

        image = findViewById(R.id.preview_image)
        spinner = findViewById(R.id.preview_spinner)
        hint = findViewById(R.id.preview_hint)

        location = intent.getStringExtra(EXTRA_LOCATION) ?: ""
        current = Prefs.getStyle(this)

        val uri = intent.getParcelableExtra<Uri>(EXTRA_URI)
        if (uri == null) { finish(); return }

        val styleButtons = mapOf(
            "pill" to findViewById<Button>(R.id.pv_pill),
            "banner" to findViewById<Button>(R.id.pv_banner),
            "script" to findViewById<Button>(R.id.pv_script),
        )
        fun highlight() {
            styleButtons.forEach { (name, btn) ->
                val on = name == current
                btn.setBackgroundColor(if (on) 0xFF4A9EFF.toInt() else 0x00000000)
                btn.setTextColor(if (on) 0xFFFFFFFF.toInt() else 0xFFE8E8E8.toInt())
            }
        }
        styleButtons.forEach { (name, btn) ->
            btn.setOnClickListener {
                current = name
                Prefs.setStyle(this, name)
                highlight()
                renderPreview()
            }
        }
        highlight()

        findViewById<Button>(R.id.pv_use).setOnClickListener {
            Prefs.setStyle(this, current)
            finish()  // style saved; user taps Upload back on the grid
        }

        // Read the original once (EXIF intact so location matches the upload),
        // then re-preview per style. Server downsizes for the render.
        val hasMediaLocation = checkSelfPermission(
            android.Manifest.permission.ACCESS_MEDIA_LOCATION
        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        lifecycleScope.launch {
            jpeg = withContext(Dispatchers.IO) {
                ImageUtils.readOriginal(contentResolver, uri, hasMediaLocation)
            }
            if (jpeg == null) {
                hint.text = getString(R.string.preview_failed)
                hint.visibility = View.VISIBLE
                return@launch
            }
            renderPreview()
        }
    }

    private fun renderPreview() {
        val bytes = jpeg ?: return
        spinner.visibility = View.VISIBLE
        hint.visibility = View.GONE
        val pin = Prefs.getPin(this)
        val style = current
        lifecycleScope.launch {
            val rendered = withContext(Dispatchers.IO) {
                Api.preview(pin, bytes, location, style)
            }
            spinner.visibility = View.GONE
            if (rendered == null) {
                hint.text = getString(R.string.preview_failed)
                hint.visibility = View.VISIBLE
                return@launch
            }
            val bmp = withContext(Dispatchers.IO) {
                BitmapFactory.decodeByteArray(rendered, 0, rendered.size)
            }
            image.setImageBitmap(bmp)
        }
    }
}
