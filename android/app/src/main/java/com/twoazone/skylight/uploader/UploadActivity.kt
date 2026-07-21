package com.twoazone.skylight.uploader

import android.net.Uri
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView

class UploadActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_URIS = "uris"
    }

    private lateinit var uploader: Uploader
    private lateinit var adapter: UploadAdapter
    private lateinit var summary: TextView
    private lateinit var retryAllBtn: Button
    private val jobs = ArrayList<UploadJob>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_upload)
        title = getString(R.string.uploading_title)

        // Backgrounded uploads are what killed the browser flow — keep the
        // screen on so the user isn't tempted to switch away mid-batch.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        summary = findViewById(R.id.summary)
        retryAllBtn = findViewById(R.id.retry_all_btn)
        val list: RecyclerView = findViewById(R.id.upload_list)

        @Suppress("DEPRECATION")
        val uris: ArrayList<Uri> =
            intent.getParcelableArrayListExtra(EXTRA_URIS) ?: arrayListOf()

        adapter = UploadAdapter(jobs) { job -> uploader.retry(job) }
        list.layoutManager = LinearLayoutManager(this)
        list.adapter = adapter

        val hasMediaLocation = checkSelfPermission(
            android.Manifest.permission.ACCESS_MEDIA_LOCATION
        ) == android.content.pm.PackageManager.PERMISSION_GRANTED

        uploader = Uploader(
            resolver = contentResolver,
            scope = lifecycleScope,
            pin = Prefs.getPin(this),
            style = Prefs.getStyle(this),
            hasMediaLocation = hasMediaLocation,
            onUpdate = { job -> onJobUpdate(job) },
            onBadPin = {
                Toast.makeText(this, R.string.bad_pin, Toast.LENGTH_LONG).show()
            },
        )

        jobs.addAll(uris.map { UploadJob(it) })
        adapter.notifyDataSetChanged()
        uploader.enqueue(jobs)

        retryAllBtn.setOnClickListener {
            jobs.filter { it.state == JobState.FAILED }.forEach { uploader.retry(it) }
        }
        updateSummary()
    }

    private fun onJobUpdate(job: UploadJob) {
        val idx = jobs.indexOf(job)
        if (idx >= 0) adapter.notifyItemChanged(idx)
        updateSummary()
    }

    private fun updateSummary() {
        val done = jobs.count { it.state == JobState.DONE || it.state == JobState.DUPLICATE }
        val failed = jobs.count { it.state == JobState.FAILED }
        summary.text = getString(R.string.summary_fmt, done, jobs.size, failed)
        retryAllBtn.visibility = if (failed > 0) View.VISIBLE else View.GONE
    }
}
