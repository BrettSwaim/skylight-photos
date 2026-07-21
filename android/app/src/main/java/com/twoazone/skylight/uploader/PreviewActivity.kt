package com.twoazone.skylight.uploader

import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Per-photo caption positioner. Steps through the selected photos; drag the
 * caption to place it, release to see the exact server render. Style tabs set
 * the batch style. "Done" returns each photo's normalized position.
 */
class PreviewActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_URIS = "uris"
        const val EXTRA_LOCATION = "location"
        const val RESULT_POS_URIS = "pos_uris"
        const val RESULT_POS_VALS = "pos_vals"
    }

    private lateinit var image: ImageView
    private lateinit var ghost: TextView
    private lateinit var spinner: ProgressBar
    private lateinit var counter: TextView
    private lateinit var hint: TextView
    private lateinit var nextBtn: Button

    private lateinit var uris: ArrayList<Uri>
    private var index = 0
    private var location = ""
    private var current = "pill"

    // per-photo state
    private var originalBytes: ByteArray? = null
    private var cleanBmp: android.graphics.Bitmap? = null
    private val posMap = HashMap<String, FloatArray>()  // uri -> [x, y]
    private var renderJob: Job? = null
    private var dragging = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_preview)
        title = getString(R.string.preview_title)

        image = findViewById(R.id.preview_image)
        ghost = findViewById(R.id.preview_ghost)
        spinner = findViewById(R.id.preview_spinner)
        counter = findViewById(R.id.preview_counter)
        hint = findViewById(R.id.preview_hint)
        nextBtn = findViewById(R.id.pv_use)

        location = intent.getStringExtra(EXTRA_LOCATION) ?: ""
        current = Prefs.getStyle(this)
        uris = intent.getParcelableArrayListExtra(EXTRA_URIS) ?: arrayListOf()
        if (uris.isEmpty()) { finish(); return }

        // neutral target marker (a translucent dot) — NOT a fake caption, so it
        // never misrepresents the selected style
        ghost.background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(Color.argb(150, 74, 158, 255))
            setStroke(6, Color.argb(230, 255, 255, 255))
        }
        ghost.text = "＋"
        ghost.setTextColor(Color.WHITE)
        ghost.textSize = 22f

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
                renderExact()
            }
        }
        highlight()

        nextBtn.setOnClickListener { advance() }
        setupDrag()
        loadPhoto()
    }

    private fun advance() {
        if (index < uris.size - 1) {
            index++
            loadPhoto()
        } else {
            val u = ArrayList<String>()
            val v = ArrayList<String>()
            posMap.forEach { (uri, p) -> u.add(uri); v.add("${p[0]},${p[1]}") }
            val data = android.content.Intent()
            data.putStringArrayListExtra(RESULT_POS_URIS, u)
            data.putStringArrayListExtra(RESULT_POS_VALS, v)
            setResult(RESULT_OK, data)
            finish()
        }
    }

    private fun loadPhoto() {
        counter.text = "${index + 1}/${uris.size}"
        nextBtn.text = if (index == uris.size - 1) getString(R.string.preview_done)
                       else getString(R.string.preview_next)
        ghost.visibility = View.GONE
        image.setImageBitmap(null)
        spinner.visibility = View.VISIBLE

        val uri = uris[index]
        val hasMediaLoc = checkSelfPermission(
            android.Manifest.permission.ACCESS_MEDIA_LOCATION
        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        lifecycleScope.launch {
            originalBytes = withContext(Dispatchers.IO) {
                ImageUtils.readOriginal(contentResolver, uri, hasMediaLoc)
            }
            val bytes = originalBytes
            if (bytes == null) {
                spinner.visibility = View.GONE
                hint.text = getString(R.string.preview_failed)
                hint.visibility = View.VISIBLE
                return@launch
            }
            cleanBmp = withContext(Dispatchers.IO) {
                val o = BitmapFactory.Options().apply { inSampleSize = 2 }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, o)
            }
            renderExact()
        }
    }

    /** Render the exact server preview at the current photo's stored position. */
    private fun renderExact() {
        val bytes = originalBytes ?: return
        val uri = uris[index].toString()
        val pos = posMap[uri]
        spinner.visibility = View.VISIBLE
        hint.visibility = View.GONE
        val pin = Prefs.getPin(this)
        val style = current
        val loc = location
        renderJob?.cancel()
        renderJob = lifecycleScope.launch {
            val rendered = withContext(Dispatchers.IO) {
                Api.preview(pin, bytes, loc, style, pos?.get(0), pos?.get(1))
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
            if (!dragging) image.setImageBitmap(bmp)
        }
    }

    /** Map a touch point to the fitCenter image rect → normalized (0..1). */
    private fun toNormalized(tx: Float, ty: Float): FloatArray? {
        val bmp = cleanBmp ?: return null
        val vw = image.width.toFloat()
        val vh = image.height.toFloat()
        if (vw <= 0 || vh <= 0) return null
        val scale = minOf(vw / bmp.width, vh / bmp.height)
        val dw = bmp.width * scale
        val dh = bmp.height * scale
        val offX = (vw - dw) / 2f
        val offY = (vh - dh) / 2f
        val nx = ((tx - offX) / dw).coerceIn(0f, 1f)
        val ny = ((ty - offY) / dh).coerceIn(0f, 1f)
        return floatArrayOf(nx, ny)
    }

    private fun setupDrag() {
        image.setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> {
                    dragging = true
                    // keep the real caption on screen; only show a target marker
                    ghost.visibility = View.VISIBLE
                    moveGhost(e.x, e.y)
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    moveGhost(e.x, e.y)
                    true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    dragging = false
                    val norm = toNormalized(e.x, e.y)
                    if (norm != null) {
                        posMap[uris[index].toString()] = norm
                    }
                    ghost.visibility = View.GONE
                    renderExact()
                    true
                }
                else -> false
            }
        }
    }

    private fun moveGhost(tx: Float, ty: Float) {
        // center the ghost chip on the finger, kept within the image
        val gw = ghost.width.takeIf { it > 0 } ?: 200
        val gh = ghost.height.takeIf { it > 0 } ?: 90
        ghost.x = (tx - gw / 2f).coerceIn(0f, (image.width - gw).toFloat())
        ghost.y = (ty - gh / 2f).coerceIn(0f, (image.height - gh).toFloat())
    }
}
