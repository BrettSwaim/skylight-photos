package com.twoazone.skylight.uploader

import android.Manifest
import android.content.ContentUris
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.text.InputType
import android.view.Menu
import android.view.MenuItem
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {

    private lateinit var grid: RecyclerView
    private lateinit var uploadBtn: Button
    private lateinit var adapter: GridAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Share-sheet entry: forward straight to the upload queue
        val shared = extractSharedUris(intent)
        if (shared.isNotEmpty()) {
            ensurePin { startUpload(shared) }
            return
        }

        setContentView(R.layout.activity_main)
        grid = findViewById(R.id.photo_grid)
        uploadBtn = findViewById(R.id.upload_btn)

        adapter = GridAdapter { count ->
            uploadBtn.isEnabled = count > 0
            uploadBtn.text = if (count > 0) getString(R.string.upload_n, count)
                             else getString(R.string.upload)
        }
        val layout = GridLayoutManager(this, GridAdapter.SPAN_COUNT)
        layout.spanSizeLookup = object : GridLayoutManager.SpanSizeLookup() {
            override fun getSpanSize(position: Int) = adapter.spanSize(position)
        }
        grid.layoutManager = layout
        grid.adapter = adapter

        uploadBtn.setOnClickListener {
            val uris = adapter.selectedUris()
            if (uris.isEmpty()) return@setOnClickListener
            ensurePin {
                startUpload(uris)
                adapter.clearSelection()
            }
        }

        requestPermissionsThenLoad()
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, getString(R.string.change_pin))
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == 1) {
            promptPin(force = true) {}
            return true
        }
        return super.onOptionsItemSelected(item)
    }

    private fun extractSharedUris(intent: Intent): ArrayList<Uri> {
        val uris = ArrayList<Uri>()
        when (intent.action) {
            Intent.ACTION_SEND ->
                @Suppress("DEPRECATION")
                (intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))?.let { uris.add(it) }
            Intent.ACTION_SEND_MULTIPLE ->
                @Suppress("DEPRECATION")
                intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.let { uris.addAll(it) }
        }
        return uris
    }

    private fun startUpload(uris: ArrayList<Uri>) {
        val i = Intent(this, UploadActivity::class.java)
        i.putParcelableArrayListExtra(UploadActivity.EXTRA_URIS, uris)
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        startActivity(i)
    }

    // --- PIN ---

    private fun ensurePin(then: () -> Unit) {
        if (Prefs.getPin(this).isNotEmpty()) then() else promptPin(force = false, then)
    }

    private fun promptPin(force: Boolean, then: () -> Unit) {
        val input = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
            hint = getString(R.string.pin_hint)
            if (force) setText(Prefs.getPin(this@MainActivity))
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.enter_pin)
            .setView(input)
            .setPositiveButton(android.R.string.ok) { _, _ ->
                val pin = input.text.toString().trim()
                lifecycleScope.launch {
                    val ok = withContext(Dispatchers.IO) {
                        try { Api.verifyPin(pin) } catch (_: Exception) { false }
                    }
                    if (ok) {
                        Prefs.setPin(this@MainActivity, pin)
                        then()
                    } else {
                        Toast.makeText(this@MainActivity, R.string.bad_pin, Toast.LENGTH_LONG).show()
                    }
                }
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    // --- Permissions + media loading ---

    private fun neededPermissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= 33) arrayOf(
            Manifest.permission.READ_MEDIA_IMAGES,
            Manifest.permission.READ_MEDIA_VIDEO,
            Manifest.permission.ACCESS_MEDIA_LOCATION,
        ) else arrayOf(
            Manifest.permission.READ_EXTERNAL_STORAGE,
            Manifest.permission.ACCESS_MEDIA_LOCATION,
        )

    private fun requestPermissionsThenLoad() {
        val missing = neededPermissions().filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isEmpty()) loadMedia()
        else requestPermissions(missing.toTypedArray(), 100)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 100) {
            if (grantResults.any { it == PackageManager.PERMISSION_GRANTED }) loadMedia()
            else Toast.makeText(this, R.string.need_permission, Toast.LENGTH_LONG).show()
        }
    }

    override fun onResume() {
        super.onResume()
        refreshUploadedBadges()
    }

    private fun refreshUploadedBadges() {
        if (!::adapter.isInitialized) return
        lifecycleScope.launch(Dispatchers.IO) {
            val names = try { Api.uploadedNames() } catch (_: Exception) { emptySet() }
            withContext(Dispatchers.Main) { adapter.setUploaded(names) }
        }
    }

    private fun loadMedia() {
        lifecycleScope.launch(Dispatchers.IO) {
            val items = ArrayList<GridItem>()
            val collection = MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL)
            val projection = arrayOf(
                MediaStore.Files.FileColumns._ID,
                MediaStore.Files.FileColumns.MEDIA_TYPE,
                MediaStore.Files.FileColumns.DISPLAY_NAME,
                MediaStore.Files.FileColumns.DATE_TAKEN,
                MediaStore.Files.FileColumns.DATE_ADDED,
                MediaStore.Files.FileColumns.WIDTH,
                MediaStore.Files.FileColumns.HEIGHT,
                MediaStore.Files.FileColumns.ORIENTATION,
            )
            val selection = "${MediaStore.Files.FileColumns.MEDIA_TYPE} IN (?, ?)"
            val args = arrayOf(
                MediaStore.Files.FileColumns.MEDIA_TYPE_IMAGE.toString(),
                MediaStore.Files.FileColumns.MEDIA_TYPE_VIDEO.toString(),
            )
            contentResolver.query(
                collection, projection, selection, args,
                "${MediaStore.Files.FileColumns.DATE_TAKEN} DESC, " +
                    "${MediaStore.Files.FileColumns.DATE_ADDED} DESC",
            )?.use { c ->
                val idIdx = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns._ID)
                val typeIdx = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns.MEDIA_TYPE)
                val nameIdx = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns.DISPLAY_NAME)
                val takenIdx = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns.DATE_TAKEN)
                val addedIdx = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns.DATE_ADDED)
                val wIdx = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns.WIDTH)
                val hIdx = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns.HEIGHT)
                val oIdx = c.getColumnIndexOrThrow(MediaStore.Files.FileColumns.ORIENTATION)
                while (c.moveToNext()) {
                    val id = c.getLong(idIdx)
                    val isVideo =
                        c.getInt(typeIdx) == MediaStore.Files.FileColumns.MEDIA_TYPE_VIDEO
                    val uri = if (isVideo)
                        ContentUris.withAppendedId(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, id)
                    else
                        ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id)
                    val taken = c.getLong(takenIdx)
                    val date = if (taken > 0) taken else c.getLong(addedIdx) * 1000
                    // Swap dimensions for 90/270-rotated media so pano
                    // detection uses display orientation
                    var w = c.getInt(wIdx)
                    var h = c.getInt(hIdx)
                    val orientation = c.getInt(oIdx)
                    if (orientation == 90 || orientation == 270) {
                        val t = w; w = h; h = t
                    }
                    items.add(GridItem(uri, isVideo, c.getString(nameIdx) ?: "", date, w, h))
                }
            }

            // Group by calendar day with header rows
            val fmt = java.text.SimpleDateFormat("EEE, MMM d, yyyy", java.util.Locale.US)
            val dayFmt = java.text.SimpleDateFormat("yyyyDDD", java.util.Locale.US)
            val rows = ArrayList<Row>()
            var lastDay = ""
            for (item in items) {
                val day = dayFmt.format(java.util.Date(item.dateMillis))
                if (day != lastDay) {
                    rows.add(Row.Header(fmt.format(java.util.Date(item.dateMillis))))
                    lastDay = day
                }
                rows.add(Row.Media(item))
            }

            withContext(Dispatchers.Main) {
                adapter.submit(rows)
                refreshUploadedBadges()
            }
        }
    }
}
