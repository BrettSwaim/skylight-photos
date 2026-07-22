package com.twoazone.skylight.uploader

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

class ManageAdapter(
    private val onSelectionChanged: () -> Unit,
    private val onOpen: (Int) -> Unit,
) : RecyclerView.Adapter<ManageAdapter.Holder>() {

    private val items = ArrayList<MediaItem>()
    private val selected = LinkedHashSet<String>()  // ids
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    fun items(): List<MediaItem> = items

    fun submit(newItems: List<MediaItem>) {
        items.clear()
        items.addAll(newItems)
        selected.clear()
        notifyDataSetChanged()
    }

    fun selected(): List<MediaItem> = items.filter { selected.contains(it.id) }

    private fun toggle(id: String) {
        if (selected.contains(id)) selected.remove(id) else selected.add(id)
        notifyDataSetChanged()
        onSelectionChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
        val v = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_manage, parent, false)
        return Holder(v)
    }

    override fun getItemCount() = items.size

    override fun onBindViewHolder(holder: Holder, position: Int) = holder.bind(items[position])

    inner class Holder(view: View) : RecyclerView.ViewHolder(view) {
        private val thumb: ImageView = view.findViewById(R.id.m_thumb)
        private val check: TextView = view.findViewById(R.id.m_check)
        private val videoBadge: TextView = view.findViewById(R.id.m_video)
        private val styleBadge: TextView = view.findViewById(R.id.m_style)
        private var loadJob: Job? = null

        fun bind(item: MediaItem) {
            val isSel = selected.contains(item.id)
            check.visibility = if (isSel) View.VISIBLE else View.GONE
            thumb.alpha = if (isSel) 0.5f else 1.0f
            videoBadge.visibility = if (item.isImage) View.GONE else View.VISIBLE
            styleBadge.visibility = if (item.captionStyle != null) View.VISIBLE else View.GONE
            styleBadge.text = item.captionStyle ?: ""

            thumb.setImageBitmap(UrlImageLoader.cached(item.fileUrl))
            if (UrlImageLoader.cached(item.fileUrl) == null) {
                loadJob?.cancel()
                loadJob = scope.launch {
                    val bmp = withContext(Dispatchers.IO) { UrlImageLoader.load(item.fileUrl) }
                    if (bmp != null && bindingAdapterPosition != RecyclerView.NO_POSITION &&
                        items[bindingAdapterPosition].id == item.id
                    ) thumb.setImageBitmap(bmp)
                }
            }

            // Tap opens the full-screen viewer UNLESS a selection is active,
            // in which case tap continues the selection (standard gallery behavior).
            itemView.setOnClickListener {
                if (selected.isNotEmpty()) {
                    toggle(item.id)
                } else {
                    val pos = bindingAdapterPosition
                    if (pos != RecyclerView.NO_POSITION) onOpen(pos)
                }
            }
            itemView.setOnLongClickListener {
                toggle(item.id)
                true
            }
        }
    }
}
