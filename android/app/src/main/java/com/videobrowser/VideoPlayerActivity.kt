package com.videobrowser

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import com.videobrowser.databinding.ActivityPlayerBinding

class VideoPlayerActivity : AppCompatActivity() {

    private lateinit var binding: ActivityPlayerBinding
    private var player: ExoPlayer? = null
    private var videoPath: String? = null

    companion object {
        private const val EXTRA_PATH = "video_path"
        private const val EXTRA_ORIG = "orig_size"
        private const val EXTRA_COMP = "comp_size"

        fun start(
            context: Context,
            path: String,
            origSize: Long,
            compSize: Long
        ) {
            val intent = Intent(context, VideoPlayerActivity::class.java).apply {
                putExtra(EXTRA_PATH, path)
                putExtra(EXTRA_ORIG, origSize)
                putExtra(EXTRA_COMP, compSize)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityPlayerBinding.inflate(layoutInflater)
        setContentView(binding.root)

        videoPath = intent?.getStringExtra(EXTRA_PATH)
        val origSize = intent?.getLongExtra(EXTRA_ORIG, 0) ?: 0
        val compSize = intent?.getLongExtra(EXTRA_COMP, 0) ?: 0

        showStats(origSize, compSize)
        setupPlayer()
    }

    private fun showStats(origSize: Long, compSize: Long) {
        if (origSize > 0 && compSize > 0) {
            val savedBytes = origSize - compSize
            val savedPercent = ((savedBytes.toDouble() / origSize) * 100).toInt()
            val origMb = "%.1f".format(origSize / (1024.0 * 1024.0))
            val compMb = "%.1f".format(compSize / (1024.0 * 1024.0))
            val savedMb = "%.1f".format(savedBytes / (1024.0 * 1024.0))

            binding.statsLayout.visibility = android.view.View.VISIBLE
            binding.statsOriginal.text = getString(R.string.stats_original, origMb)
            binding.statsCompressed.text = getString(R.string.stats_compressed, compMb)
            binding.statsSaved.text = getString(R.string.stats_saved, savedMb, savedPercent)

            if (savedPercent > 0) {
                binding.statsSaved.setTextColor(
                    androidx.core.content.ContextCompat.getColor(this, android.R.color.holo_green_dark)
                )
            }
        } else {
            binding.statsLayout.visibility = android.view.View.GONE
        }
    }

    private fun setupPlayer() {
        val path = videoPath ?: return
        val uri = if (path.startsWith("http://") || path.startsWith("https://")) {
            Uri.parse(path)
        } else {
            Uri.fromFile(java.io.File(path))
        }

        player = ExoPlayer.Builder(this).build().also {
            it.setMediaItem(MediaItem.fromUri(uri))
            it.prepare()
            it.playWhenReady = true
            binding.playerView.player = it
        }

        binding.btnShare.setOnClickListener {
            val shareIntent = Intent(Intent.ACTION_SEND).apply {
                type = "video/mp4"
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(shareIntent, getString(R.string.share_video)))
        }
    }

    override fun onStop() {
        super.onStop()
        player?.pause()
    }

    override fun onDestroy() {
        super.onDestroy()
        player?.release()
        player = null
    }
}
