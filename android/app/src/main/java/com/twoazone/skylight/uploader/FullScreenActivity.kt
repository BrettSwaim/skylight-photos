package com.twoazone.skylight.uploader

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.viewpager2.widget.ViewPager2
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Swipeable full-screen viewer for frame media, with delete + re-style. */
class FullScreenActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_IDS = "ids"
        const val EXTRA_TYPES = "types"
        const val EXTRA_STYLES = "styles"
        const val EXTRA_MASTERS = "masters"
        const val EXTRA_START = "start"
    }

    private lateinit var pager: ViewPager2
    private lateinit var adapter: FullScreenAdapter
    private lateinit var counter: TextView
    private lateinit var restyleBtn: Button
    private val items = ArrayList<MediaItem>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_fullscreen)

        pager = findViewById(R.id.fs_pager)
        counter = findViewById(R.id.fs_counter)
        restyleBtn = findViewById(R.id.fs_restyle)
        val deleteBtn: Button = findViewById(R.id.fs_delete)

        val ids = intent.getStringArrayListExtra(EXTRA_IDS) ?: arrayListOf()
        val types = intent.getStringArrayListExtra(EXTRA_TYPES) ?: arrayListOf()
        val styles = intent.getStringArrayListExtra(EXTRA_STYLES) ?: arrayListOf()
        val masters = intent.getBooleanArrayExtra(EXTRA_MASTERS) ?: BooleanArray(ids.size)
        val start = intent.getIntExtra(EXTRA_START, 0)

        for (i in ids.indices) {
            items.add(
                MediaItem(
                    id = ids[i],
                    mediaType = types.getOrElse(i) { "image" },
                    uploadedAt = "",
                    captionStyle = styles.getOrElse(i) { "" }.ifEmpty { null },
                    hasMaster = masters.getOrElse(i) { false },
                )
            )
        }
        if (items.isEmpty()) { finish(); return }

        adapter = FullScreenAdapter(items)
        pager.adapter = adapter
        pager.setCurrentItem(start.coerceIn(0, items.size - 1), false)
        pager.registerOnPageChangeCallback(object : ViewPager2.OnPageChangeCallback() {
            override fun onPageSelected(position: Int) = updateChrome(position)
        })
        updateChrome(pager.currentItem)

        deleteBtn.setOnClickListener { confirmDelete() }
        restyleBtn.setOnClickListener { chooseRestyle() }
        findViewById<View>(R.id.fs_close).setOnClickListener { finish() }
    }

    private fun current(): MediaItem = items[pager.currentItem]

    private fun updateChrome(position: Int) {
        counter.text = "${position + 1} / ${items.size}"
        val m = items[position]
        val canRestyle = m.isImage && m.hasMaster
        restyleBtn.visibility = if (canRestyle) View.VISIBLE else View.GONE
    }

    private fun confirmDelete() {
        val m = current()
        AlertDialog.Builder(this)
            .setTitle(R.string.delete)
            .setMessage(R.string.delete_confirm)
            .setPositiveButton(R.string.delete) { _, _ -> doDelete(m) }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun doDelete(m: MediaItem) {
        val pin = Prefs.getPin(this)
        lifecycleScope.launch {
            val ok = withContext(Dispatchers.IO) { Api.deleteMedia(pin, m.id) }
            if (!ok) {
                Toast.makeText(this@FullScreenActivity, R.string.delete, Toast.LENGTH_SHORT).show()
                return@launch
            }
            UrlImageLoader.evict(m.fileUrl)
            val pos = items.indexOf(m)
            if (pos >= 0) {
                items.removeAt(pos)
                adapter.notifyItemRemoved(pos)
            }
            if (items.isEmpty()) { finish(); return@launch }
            updateChrome(pager.currentItem)
        }
    }

    private fun chooseRestyle() {
        val m = current()
        val styles = arrayOf("pill", "banner", "script")
        val labels = arrayOf(
            getString(R.string.style_pill),
            getString(R.string.style_banner),
            getString(R.string.style_script),
        )
        AlertDialog.Builder(this)
            .setTitle(R.string.restyle_title)
            .setItems(labels) { _, which -> doRestyle(m, styles[which]) }
            .show()
    }

    private fun doRestyle(m: MediaItem, style: String) {
        val pin = Prefs.getPin(this)
        lifecycleScope.launch {
            val ok = withContext(Dispatchers.IO) { Api.restyle(pin, m.id, style) }
            if (!ok) {
                Toast.makeText(this@FullScreenActivity, R.string.restyle, Toast.LENGTH_SHORT).show()
                return@launch
            }
            UrlImageLoader.evict(m.fileUrl)
            val pos = items.indexOf(m)
            if (pos >= 0) adapter.notifyItemChanged(pos)  // reloads image (cache evicted)
            Toast.makeText(this@FullScreenActivity,
                getString(R.string.restyled_n, 1), Toast.LENGTH_SHORT).show()
        }
    }
}
