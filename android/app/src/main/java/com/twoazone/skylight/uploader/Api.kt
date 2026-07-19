package com.twoazone.skylight.uploader

import java.io.InputStream
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink

/** Result of one upload attempt. */
sealed class UploadResult {
    object Ok : UploadResult()
    object Duplicate : UploadResult()
    object BadPin : UploadResult()
    /** 4xx rejection — do not retry. */
    data class Rejected(val message: String) : UploadResult()
    /** Network drop or 5xx — retriable. */
    data class Retriable(val message: String) : UploadResult()
}

object Api {
    const val BASE = "https://photos.2azone.com/api"

    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.MINUTES)
        .readTimeout(10, TimeUnit.MINUTES)
        .build()

    fun verifyPin(pin: String): Boolean {
        val body = """{"pin":"${pin.replace("\"", "")}"}"""
            .toRequestBody("application/json".toMediaType())
        val req = Request.Builder().url("$BASE/verify-pin").post(body).build()
        client.newCall(req).execute().use { resp ->
            return resp.isSuccessful && (resp.body?.string()?.contains("true") == true)
        }
    }

    /**
     * Upload one file as multipart. Streams from [streamFactory] so large
     * videos never sit fully in memory. [onProgress] gets 0-100.
     */
    fun upload(
        pin: String,
        fileName: String,
        mimeType: String,
        contentLength: Long,
        streamFactory: () -> InputStream,
        onProgress: (Int) -> Unit,
    ): UploadResult {
        val fileBody = object : RequestBody() {
            override fun contentType() = mimeType.toMediaType()
            override fun contentLength() = contentLength

            override fun writeTo(sink: BufferedSink) {
                var sent = 0L
                streamFactory().use { input ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        sink.write(buf, 0, n)
                        sent += n
                        if (contentLength > 0) {
                            onProgress(((sent * 100) / contentLength).toInt().coerceAtMost(100))
                        }
                    }
                }
            }
        }

        val multipart = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", fileName, fileBody)
            .build()

        val req = Request.Builder()
            .url("$BASE/upload")
            .header("X-Upload-PIN", pin)
            .post(multipart)
            .build()

        return try {
            client.newCall(req).execute().use { resp ->
                when {
                    resp.isSuccessful -> UploadResult.Ok
                    resp.code == 409 -> UploadResult.Duplicate
                    resp.code == 403 -> UploadResult.BadPin
                    resp.code in 400..499 ->
                        UploadResult.Rejected(extractDetail(resp.body?.string()) ?: "Rejected (${resp.code})")
                    else -> UploadResult.Retriable("Server error (${resp.code})")
                }
            }
        } catch (e: java.io.IOException) {
            UploadResult.Retriable(e.message ?: "Network error")
        }
    }

    private fun extractDetail(body: String?): String? {
        if (body == null) return null
        val m = Regex("\"detail\"\\s*:\\s*\"([^\"]+)\"").find(body)
        return m?.groupValues?.get(1)
    }

    /** original_name of everything already on the server, for grid badges. */
    fun uploadedNames(): Set<String> {
        val req = Request.Builder().url("$BASE/media").get().build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return emptySet()
            val body = resp.body?.string() ?: return emptySet()
            val names = HashSet<String>()
            val arr = org.json.JSONObject(body).optJSONArray("media") ?: return emptySet()
            for (i in 0 until arr.length()) {
                arr.optJSONObject(i)?.optString("original_name")?.let {
                    if (it.isNotEmpty()) names.add(it)
                }
            }
            return names
        }
    }
}
