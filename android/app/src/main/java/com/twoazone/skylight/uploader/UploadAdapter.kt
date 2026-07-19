package com.twoazone.skylight.uploader

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

class UploadAdapter(
    private val jobs: List<UploadJob>,
    private val onRetry: (UploadJob) -> Unit,
) : RecyclerView.Adapter<UploadAdapter.Holder>() {

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
        val v = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_upload, parent, false)
        return Holder(v)
    }

    override fun getItemCount() = jobs.size

    override fun onBindViewHolder(holder: Holder, position: Int) {
        holder.bind(jobs[position])
    }

    inner class Holder(view: View) : RecyclerView.ViewHolder(view) {
        private val name: TextView = view.findViewById(R.id.file_name)
        private val status: TextView = view.findViewById(R.id.file_status)
        private val progress: ProgressBar = view.findViewById(R.id.file_progress)
        private val retryBtn: Button = view.findViewById(R.id.retry_btn)

        fun bind(job: UploadJob) {
            name.text = job.name
            progress.progress = job.progress
            retryBtn.visibility = View.GONE

            val ctx = itemView.context
            when (job.state) {
                JobState.QUEUED -> status.text = ctx.getString(R.string.queued)
                JobState.UPLOADING -> status.text =
                    if (job.message.isNotEmpty()) job.message else "${job.progress}%"
                JobState.DONE -> status.text = ctx.getString(R.string.done)
                JobState.DUPLICATE -> status.text = ctx.getString(R.string.already_uploaded)
                JobState.FAILED -> {
                    status.text = job.message
                    retryBtn.visibility = View.VISIBLE
                    retryBtn.setOnClickListener { onRetry(job) }
                }
            }
        }
    }
}
