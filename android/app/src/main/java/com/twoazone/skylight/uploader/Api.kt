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
        style: String,
        posX: Float?,
        posY: Float?,
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
            .addFormDataPart("style", style)
            .apply {
                if (posX != null && posY != null) {
                    addFormDataPart("pos_x", posX.toString())
                    addFormDataPart("pos_y", posY.toString())
                }
            }
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

    /** Render a caption preview server-side. Returns JPEG bytes or null on failure. */
    fun preview(
        pin: String, jpeg: ByteArray, location: String, style: String,
        posX: Float? = null, posY: Float? = null,
    ): ByteArray? {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file", "preview.jpg",
                jpeg.toRequestBody("image/jpeg".toMediaType())
            )
            .addFormDataPart("style", style)
            .apply {
                if (location.isNotBlank()) addFormDataPart("location", location)
                if (posX != null && posY != null) {
                    addFormDataPart("pos_x", posX.toString())
                    addFormDataPart("pos_y", posY.toString())
                }
            }
            .build()
        val req = Request.Builder()
            .url("$BASE/preview")
            .header("X-Upload-PIN", pin)
            .post(body)
            .build()
        return try {
            client.newCall(req).execute().use { resp ->
                if (resp.isSuccessful) resp.body?.bytes() else null
            }
        } catch (_: java.io.IOException) {
            null
        }
    }

    /** Full media list (id, filename, type, caption_style, master_filename). */
    fun listMedia(): List<MediaItem> {
        val req = Request.Builder().url("$BASE/media").get().build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return emptyList()
            val body = resp.body?.string() ?: return emptyList()
            val arr = org.json.JSONObject(body).optJSONArray("media") ?: return emptyList()
            val out = ArrayList<MediaItem>(arr.length())
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                out.add(
                    MediaItem(
                        id = o.optString("id"),
                        mediaType = o.optString("media_type"),
                        uploadedAt = o.optString("uploaded_at"),
                        captionStyle = o.optString("caption_style").ifEmpty { null },
                        hasMaster = !o.isNull("master_filename") &&
                            o.optString("master_filename").isNotEmpty(),
                    )
                )
            }
            return out
        }
    }

    fun deleteMedia(pin: String, id: String): Boolean {
        val req = Request.Builder()
            .url("$BASE/media/$id")
            .header("X-Upload-PIN", pin)
            .delete()
            .build()
        return try {
            client.newCall(req).execute().use { it.isSuccessful || it.code == 404 }
        } catch (_: java.io.IOException) {
            false
        }
    }

    fun restyle(pin: String, id: String, style: String): Boolean {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("style", style)
            .build()
        val req = Request.Builder()
            .url("$BASE/media/$id/restyle")
            .header("X-Upload-PIN", pin)
            .post(body)
            .build()
        return try {
            client.newCall(req).execute().use { it.isSuccessful }
        } catch (_: java.io.IOException) {
            false
        }
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
