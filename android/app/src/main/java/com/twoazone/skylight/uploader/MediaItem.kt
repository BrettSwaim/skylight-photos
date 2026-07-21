package com.twoazone.skylight.uploader

/** A photo/video already on the frame (from /api/media). */
data class MediaItem(
    val id: String,
    val mediaType: String,
    val uploadedAt: String,
    val captionStyle: String?,
    val hasMaster: Boolean,
) {
    val isImage: Boolean get() = mediaType == "image"
    val fileUrl: String get() = "${Api.BASE}/media/$id/file"
}
