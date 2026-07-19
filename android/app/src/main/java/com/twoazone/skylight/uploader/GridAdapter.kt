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

data class GridItem(val uri: Uri, val isVideo: Boolean)

class GridAdapter(
    private val onSelectionChanged: (Int) -> Unit,
) : RecyclerView.Adapter<GridAdapter.Holder>() {

    private val items = ArrayList<GridItem>()
    private val selected = LinkedHashSet<Uri>()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val thumbCache = LruCache<Uri, Bitmap>(200)

    fun submit(newItems: List<GridItem>) {
        items.clear()
        items.addAll(newItems)
        notifyDataSetChanged()
    }

    fun selectedUris(): ArrayList<Uri> = ArrayList(selected)

    fun clearSelection() {
        selected.clear()
        onSelectionChanged(0)
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
        val v = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_photo, parent, false)
        return Holder(v)
    }

    override fun getItemCount() = items.size

    override fun onBindViewHolder(holder: Holder, position: Int) {
        holder.bind(items[position])
    }

    inner class Holder(view: View) : RecyclerView.ViewHolder(view) {
        private val thumb: ImageView = view.findViewById(R.id.thumb)
        private val check: TextView = view.findViewById(R.id.check)
        private val videoBadge: TextView = view.findViewById(R.id.video_badge)
        private var loadJob: Job? = null

        fun bind(item: GridItem) {
            val isSelected = selected.contains(item.uri)
            check.visibility = if (isSelected) View.VISIBLE else View.GONE
            thumb.alpha = if (isSelected) 0.5f else 1.0f
            videoBadge.visibility = if (item.isVideo) View.VISIBLE else View.GONE

            thumb.setImageBitmap(null)
            val cached = thumbCache.get(item.uri)
            if (cached != null) {
                thumb.setImageBitmap(cached)
            } else {
                loadJob?.cancel()
                loadJob = scope.launch {
                    val bmp = withContext(Dispatchers.IO) {
                        try {
                            itemView.context.contentResolver
                                .loadThumbnail(item.uri, Size(256, 256), null)
                        } catch (_: Exception) { null }
                    }
                    if (bmp != null) {
                        thumbCache.put(item.uri, bmp)
                        // Only set if this holder still shows the same item
                        if (bindingAdapterPosition != RecyclerView.NO_POSITION &&
                            items[bindingAdapterPosition].uri == item.uri
                        ) {
                            thumb.setImageBitmap(bmp)
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
