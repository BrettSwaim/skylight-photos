package com.twoazone.skylight.uploader

import android.content.ContentResolver
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.MediaStore
import android.util.LruCache
import okhttp3.OkHttpClient
import okhttp3.Request

object ImageUtils {
    /**
     * Read the original image bytes (EXIF intact) so the preview's caption
     * location/date matches the real upload. Uses setRequireOriginal when
     * media-location permission is held; falls back to the plain stream.
     */
    fun readOriginal(resolver: ContentResolver, uri: Uri, hasMediaLocation: Boolean): ByteArray? {
        return try {
            val src = if (hasMediaLocation) {
                try { MediaStore.setRequireOriginal(uri) } catch (_: Exception) { uri }
            } else uri
            resolver.openInputStream(src)?.use { it.readBytes() }
        } catch (_: Exception) {
            null
        }
    }
}

/** Minimal OkHttp + LruCache remote thumbnail loader (no Glide/Coil dependency). */
object UrlImageLoader {
    private val client = OkHttpClient()
    private val cache = LruCache<String, Bitmap>(150)

    fun cached(url: String): Bitmap? = cache.get(url)

    fun load(url: String, maxDim: Int = 400): Bitmap? {
        cache.get(url)?.let { return it }
        return try {
            val req = Request.Builder().url(url).get().build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return null
                val bytes = resp.body?.bytes() ?: return null
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
                var sample = 1
                val longest = maxOf(bounds.outWidth, bounds.outHeight)
                while (longest / sample > maxDim * 2) sample *= 2
                val opts = BitmapFactory.Options().apply { inSampleSize = sample }
                val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts)
                if (bmp != null) cache.put(url, bmp)
                bmp
            }
        } catch (_: Exception) {
            null
        }
    }

    fun evict(url: String) {
        cache.remove(url)
        fullCache.remove(url)
    }

    // Larger images for the full-screen viewer (separate from the 400px grid cache)
    private val fullCache = LruCache<String, Bitmap>(8)

    fun loadFull(url: String, maxDim: Int = 1600): Bitmap? {
        fullCache.get(url)?.let { return it }
        return try {
            val req = Request.Builder().url(url).get().build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return null
                val bytes = resp.body?.bytes() ?: return null
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
                var sample = 1
                val longest = maxOf(bounds.outWidth, bounds.outHeight)
                while (longest / sample > maxDim * 2) sample *= 2
                val opts = BitmapFactory.Options().apply { inSampleSize = sample }
                val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts)
                if (bmp != null) fullCache.put(url, bmp)
                bmp
            }
        } catch (_: Exception) {
            null
        }
    }
}
