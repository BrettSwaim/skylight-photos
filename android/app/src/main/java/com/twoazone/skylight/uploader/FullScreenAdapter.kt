package com.twoazone.skylight.uploader

import android.net.Uri
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.VideoView
import androidx.recyclerview.widget.RecyclerView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** ViewPager2 pages: full image (loadFull) or a playable video. */
class FullScreenAdapter(
    private val items: List<MediaItem>,
) : RecyclerView.Adapter<FullScreenAdapter.Holder>() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
        val v = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_fullscreen, parent, false)
        return Holder(v)
    }

    override fun getItemCount() = items.size

    override fun onBindViewHolder(holder: Holder, position: Int) = holder.bind(items[position])

    override fun onViewRecycled(holder: Holder) {
        holder.recycle()
    }

    inner class Holder(view: View) : RecyclerView.ViewHolder(view) {
        private val image: ImageView = view.findViewById(R.id.fs_image)
        private val video: VideoView = view.findViewById(R.id.fs_video)
        private val spinner: ProgressBar = view.findViewById(R.id.fs_spinner)
        private var loadJob: Job? = null

        fun bind(item: MediaItem) {
            loadJob?.cancel()
            video.stopPlayback()
            if (item.isImage) {
                video.visibility = View.GONE
                image.visibility = View.VISIBLE
                image.setImageBitmap(null)
                spinner.visibility = View.VISIBLE
                loadJob = scope.launch {
                    val bmp = withContext(Dispatchers.IO) {
                        UrlImageLoader.loadFull(item.fileUrl)
                    }
                    spinner.visibility = View.GONE
                    if (bindingAdapterPosition != RecyclerView.NO_POSITION &&
                        items[bindingAdapterPosition].id == item.id
                    ) image.setImageBitmap(bmp)
                }
            } else {
                image.visibility = View.GONE
                spinner.visibility = View.GONE
                video.visibility = View.VISIBLE
                val mc = android.widget.MediaController(video.context)
                mc.setAnchorView(video)
                video.setMediaController(mc)
                video.setVideoURI(Uri.parse(item.fileUrl))
                video.setOnPreparedListener { it.isLooping = false; video.start() }
            }
        }

        fun recycle() {
            loadJob?.cancel()
            video.stopPlayback()
            image.setImageBitmap(null)
        }
    }
}
