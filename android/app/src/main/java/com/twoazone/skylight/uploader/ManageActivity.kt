package com.twoazone.skylight.uploader

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** "On the Frame" — browse server media, multi-select delete, and re-style. */
class ManageActivity : AppCompatActivity() {

    private lateinit var adapter: ManageAdapter
    private lateinit var deleteBtn: Button
    private lateinit var restyleBtn: Button
    private lateinit var emptyText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_manage)
        title = getString(R.string.manage_title)

        val grid: RecyclerView = findViewById(R.id.manage_grid)
        deleteBtn = findViewById(R.id.manage_delete)
        restyleBtn = findViewById(R.id.manage_restyle)
        emptyText = findViewById(R.id.manage_empty)

        adapter = ManageAdapter { onSelectionChanged() }
        grid.layoutManager = GridLayoutManager(this, 3)
        grid.adapter = adapter

        deleteBtn.setOnClickListener { confirmDelete() }
        restyleBtn.setOnClickListener { chooseRestyle() }

        loadMedia()
    }

    private fun loadMedia() {
        lifecycleScope.launch {
            val items = withContext(Dispatchers.IO) {
                try { Api.listMedia() } catch (_: Exception) { emptyList() }
            }
            adapter.submit(items.sortedByDescending { it.uploadedAt })
            emptyText.visibility = if (items.isEmpty()) View.VISIBLE else View.GONE
            onSelectionChanged()
        }
    }

    private fun onSelectionChanged() {
        val sel = adapter.selected()
        val n = sel.size
        deleteBtn.isEnabled = n > 0
        deleteBtn.text = if (n > 0) getString(R.string.delete_n, n) else getString(R.string.delete)
        // Re-style enabled only when every selected item is a restylable image
        val restylable = n > 0 && sel.all { it.isImage && it.hasMaster }
        restyleBtn.isEnabled = restylable
        restyleBtn.alpha = if (restylable) 1f else 0.4f
    }

    private fun confirmDelete() {
        val sel = adapter.selected()
        if (sel.isEmpty()) return
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.delete_n, sel.size))
            .setMessage(R.string.delete_confirm)
            .setPositiveButton(R.string.delete) { _, _ -> doDelete(sel.toList()) }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun doDelete(items: List<MediaItem>) {
        val pin = Prefs.getPin(this)
        lifecycleScope.launch {
            var ok = 0
            withContext(Dispatchers.IO) {
                for (m in items) if (Api.deleteMedia(pin, m.id)) {
                    ok++
                    UrlImageLoader.evict(m.fileUrl)
                }
            }
            Toast.makeText(this@ManageActivity,
                getString(R.string.deleted_n, ok), Toast.LENGTH_SHORT).show()
            loadMedia()
        }
    }

    private fun chooseRestyle() {
        val sel = adapter.selected()
        if (sel.isEmpty()) return
        val styles = arrayOf("pill", "banner", "script")
        val labels = arrayOf(
            getString(R.string.style_pill),
            getString(R.string.style_banner),
            getString(R.string.style_script),
        )
        AlertDialog.Builder(this)
            .setTitle(R.string.restyle_title)
            .setItems(labels) { _, which -> doRestyle(sel.toList(), styles[which]) }
            .show()
    }

    private fun doRestyle(items: List<MediaItem>, style: String) {
        val pin = Prefs.getPin(this)
        lifecycleScope.launch {
            var ok = 0
            withContext(Dispatchers.IO) {
                for (m in items) if (Api.restyle(pin, m.id, style)) {
                    ok++
                    UrlImageLoader.evict(m.fileUrl)  // force re-fetch of new render
                }
            }
            Toast.makeText(this@ManageActivity,
                getString(R.string.restyled_n, ok), Toast.LENGTH_SHORT).show()
            loadMedia()
        }
    }
}
