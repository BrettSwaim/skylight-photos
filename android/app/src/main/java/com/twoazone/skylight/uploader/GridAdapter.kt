package com.twoazone.skylight.uploader

import android.graphics.Bitmap
import android.net.Uri
import android.util.LruCache
import android.util.Size
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class GridItem(
    val uri: Uri,
    val isVideo: Boolean,
    val name: String,
    val dateMillis: Long,
    val width: Int,
    val height: Int,
) {
    /** Wide enough that cropping would hide what it is. */
    val isPano: Boolean
        get() = width > 0 && height > 0 && width.toFloat() / height >= 2.2f
}

sealed class Row {
    data class Header(val label: String) : Row()
    data class Media(val item: GridItem) : Row()
}

class GridAdapter(
    private val onSelectionChanged: (Int) -> Unit,
) : RecyclerView.Adapter<RecyclerView.ViewHolder>() {

    companion object {
        const val TYPE_HEADER = 0
        const val TYPE_MEDIA = 1
        const val TYPE_PANO = 2
        const val SPAN_COUNT = 4
    }

    private val rows = ArrayList<Row>()
    private val selected = LinkedHashSet<Uri>()
    private var uploadedNames: Set<String> = emptySet()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val thumbCache = LruCache<Uri, Bitmap>(200)

    fun submit(newRows: List<Row>) {
        rows.clear()
        rows.addAll(newRows)
        notifyDataSetChanged()
    }

    fun setUploaded(names: Set<String>) {
        uploadedNames = names
        notifyDataSetChanged()
    }

    fun selectedUris(): ArrayList<Uri> = ArrayList(selected)

    fun clearSelection() {
        selected.clear()
        onSelectionChanged(0)
        notifyDataSetChanged()
    }

    fun spanSize(position: Int): Int = when (getItemViewType(position)) {
        TYPE_HEADER, TYPE_PANO -> SPAN_COUNT
        else -> 1
    }

    override fun getItemViewType(position: Int): Int = when (val row = rows[position]) {
        is Row.Header -> TYPE_HEADER
        is Row.Media -> if (row.item.isPano) TYPE_PANO else TYPE_MEDIA
    }

    override fun getItemCount() = rows.size

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
        val inflater = LayoutInflater.from(parent.context)
        return when (viewType) {
            TYPE_HEADER -> HeaderHolder(inflater.inflate(R.layout.item_header, parent, false))
            TYPE_PANO -> MediaHolder(inflater.inflate(R.layout.item_photo_pano, parent, false))
            else -> MediaHolder(inflater.inflate(R.layout.item_photo, parent, false))
        }
    }

    override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
        when (val row = rows[position]) {
            is Row.Header -> (holder as HeaderHolder).bind(row.label)
            is Row.Media -> (holder as MediaHolder).bind(row.item)
        }
    }

    inner class HeaderHolder(view: View) : RecyclerView.ViewHolder(view) {
        private val label: TextView = view.findViewById(R.id.header_label)
        fun bind(text: String) { label.text = text }
    }

    inner class MediaHolder(view: View) : RecyclerView.ViewHolder(view) {
        private val thumb: ImageView = view.findViewById(R.id.thumb)
        private val check: TextView = view.findViewById(R.id.check)
        private val videoBadge: TextView = view.findViewById(R.id.video_badge)
        private val uploadedBadge: TextView = view.findViewById(R.id.uploaded_badge)
        private var loadJob: Job? = null

        fun bind(item: GridItem) {
            val isSelected = selected.contains(item.uri)
            check.visibility = if (isSelected) View.VISIBLE else View.GONE
            thumb.alpha = if (isSelected) 0.5f else 1.0f
            videoBadge.visibility = if (item.isVideo) View.VISIBLE else View.GONE
            uploadedBadge.visibility =
                if (uploadedNames.contains(item.name)) View.VISIBLE else View.GONE

            thumb.setImageBitmap(null)
            val cached = thumbCache.get(item.uri)
            if (cached != null) {
                thumb.setImageBitmap(cached)
            } else {
                loadJob?.cancel()
                val size = if (item.isPano) Size(1024, 512) else Size(384, 384)
                loadJob = scope.launch {
                    val bmp = withContext(Dispatchers.IO) {
                        try {
                            itemView.context.contentResolver
                                .loadThumbnail(item.uri, size, null)
                        } catch (_: Exception) { null }
                    }
                    if (bmp != null) {
                        thumbCache.put(item.uri, bmp)
                        val pos = bindingAdapterPosition
                        if (pos != RecyclerView.NO_POSITION) {
                            val row = rows[pos]
                            if (row is Row.Media && row.item.uri == item.uri) {
                                thumb.setImageBitmap(bmp)
                            }
                        }
                    }
                }
            }

            itemView.setOnClickListener {
                if (selected.contains(item.uri)) selected.remove(item.uri)
                else selected.add(item.uri)
                notifyItemChanged(bindingAdapterPosition)
                onSelectionChanged(selected.size)
            }
        }
    }
}
