package com.twoazone.skylight.uploader

import android.content.ContentResolver
import android.net.Uri
import android.provider.MediaStore
import android.provider.OpenableColumns
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext

enum class JobState { QUEUED, UPLOADING, DONE, DUPLICATE, FAILED }

class UploadJob(val uri: Uri) {
    var name: String = "unknown"
    var mime: String = "application/octet-stream"
    var size: Long = -1
    var state: JobState = JobState.QUEUED
    var progress: Int = 0
    var message: String = ""
    var attempts: Int = 0
}

/**
 * Bounded upload queue mirroring the web frontend's semantics:
 * 3 concurrent, 2 auto-retries with backoff for network/5xx failures,
 * 409 duplicate treated as success.
 */
class Uploader(
    private val resolver: ContentResolver,
    private val scope: CoroutineScope,
    private val pin: String,
    private val style: String,
    private val hasMediaLocation: Boolean,
    private val onUpdate: (UploadJob) -> Unit,
    private val onBadPin: () -> Unit,
) {
    companion object {
        const val MAX_CONCURRENT = 3
        const val MAX_ATTEMPTS = 3
    }

    private val semaphore = Semaphore(MAX_CONCURRENT)

    fun enqueue(jobs: List<UploadJob>) {
        for (job in jobs) {
            resolveMeta(job)
            onUpdate(job)
            launchJob(job)
        }
    }

    fun retry(job: UploadJob) {
        job.attempts = 0
        job.progress = 0
        job.state = JobState.QUEUED
        job.message = ""
        onUpdate(job)
        launchJob(job)
    }

    private fun launchJob(job: UploadJob) {
        scope.launch(Dispatchers.IO) {
            semaphore.withPermit { run(job) }
        }
    }

    private suspend fun run(job: UploadJob) {
        while (true) {
            job.attempts++
            job.state = JobState.UPLOADING
            job.progress = 0
            post(job)

            val result = Api.upload(
                pin = pin,
                fileName = job.name,
                mimeType = job.mime,
                contentLength = job.size,
                style = style,
                streamFactory = { openOriginal(job.uri) },
                onProgress = { pct ->
                    if (pct != job.progress) {
                        job.progress = pct
                        post(job)
                    }
                },
            )

            when (result) {
                is UploadResult.Ok -> {
                    job.state = JobState.DONE
                    job.progress = 100
                    post(job)
                    return
                }
                is UploadResult.Duplicate -> {
                    job.state = JobState.DUPLICATE
                    job.progress = 100
                    job.message = "Already uploaded"
                    post(job)
                    return
                }
                is UploadResult.BadPin -> {
                    job.state = JobState.FAILED
                    job.message = "Invalid PIN"
                    post(job)
                    withContext(Dispatchers.Main) { onBadPin() }
                    return
                }
                is UploadResult.Rejected -> {
                    job.state = JobState.FAILED
                    job.message = result.message
                    post(job)
                    return
                }
                is UploadResult.Retriable -> {
                    if (job.attempts >= MAX_ATTEMPTS) {
                        job.state = JobState.FAILED
                        job.message = result.message
                        post(job)
                        return
                    }
                    job.message = "Retrying (${job.attempts}/${MAX_ATTEMPTS - 1})..."
                    post(job)
                    delay(1500L * job.attempts)
                }
            }
        }
    }

    /**
     * Open the unredacted original when possible. setRequireOriginal only
     * works for MediaStore URIs with ACCESS_MEDIA_LOCATION granted; shared
     * content from other apps falls back to the plain stream.
     */
    private fun openOriginal(uri: Uri): java.io.InputStream {
        if (hasMediaLocation) {
            try {
                val original = MediaStore.setRequireOriginal(uri)
                return resolver.openInputStream(original)
                    ?: throw java.io.IOException("Cannot open $uri")
            } catch (_: Exception) {
                // Not a MediaStore URI (share target) — fall through
            }
        }
        return resolver.openInputStream(uri)
            ?: throw java.io.IOException("Cannot open $uri")
    }

    private fun resolveMeta(job: UploadJob) {
        job.mime = resolver.getType(job.uri) ?: "application/octet-stream"
        resolver.query(job.uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val nameIdx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIdx = c.getColumnIndex(OpenableColumns.SIZE)
                if (nameIdx >= 0) c.getString(nameIdx)?.let { job.name = it }
                if (sizeIdx >= 0 && !c.isNull(sizeIdx)) job.size = c.getLong(sizeIdx)
            }
        }
    }

    private fun post(job: UploadJob) {
        scope.launch(Dispatchers.Main) { onUpdate(job) }
    }
}
