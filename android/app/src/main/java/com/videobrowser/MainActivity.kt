package com.videobrowser

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.os.Bundle
import android.view.View
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.videobrowser.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONException

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var compressor: VideoCompressor
    private val videoUrls = mutableListOf<String>()

    companion object {
        private val VIDEO_EXT = Regex(
            "\\.(mp4|webm|m3u8|ts|mkv|avi|mov)(\\?.*)?$",
            RegexOption.IGNORE_CASE
        )
    }

    private val VIDEO_DETECT_JS = """
        (function() {
            var urls = [];
            document.querySelectorAll('video').forEach(function(v) {
                if (v.src) urls.push(v.src);
                v.querySelectorAll('source').forEach(function(s) {
                    if (s.src) urls.push(s.src);
                });
            });
            return urls;
        })();
    """.trimIndent()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        compressor = VideoCompressor(this)

        setupWebView()
        setupToolbar()
        handleIntent()

        binding.webview.loadUrl("https://www.bing.com")
    }

    private fun handleIntent() {
        intent?.data?.toString()?.let { url ->
            binding.webview.post { binding.webview.loadUrl(url) }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        binding.webview.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            useWideViewPort = true
            loadWithOverviewMode = true
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            userAgentString = "$userAgentString VideoCompressBrowser/1.0"
            cacheMode = WebSettings.LOAD_DEFAULT
        }

        binding.webview.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
                binding.urlBar.setText(url)
                binding.statusText.setText(R.string.status_loading)
                videoUrls.clear()
                binding.videoBanner.visibility = View.GONE
            }

            override fun onPageFinished(view: WebView, url: String) {
                binding.statusText.setText(R.string.status_compression_ready)
                detectVideos(view)
            }

            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest
            ): Boolean {
                val url = request.url.toString()
                if (VIDEO_EXT.containsMatchIn(url)) {
                    promptCompressVideo(url)
                    return true
                }
                return false
            }
        }

        binding.webview.webChromeClient = object : WebChromeClient() {
            override fun onReceivedTitle(view: WebView, title: String) {
                supportActionBar?.title = title
            }
        }
    }

    private fun setupToolbar() {
        binding.btnBack.setOnClickListener {
            if (binding.webview.canGoBack()) binding.webview.goBack()
        }
        binding.btnForward.setOnClickListener {
            if (binding.webview.canGoForward()) binding.webview.goForward()
        }
        binding.btnRefresh.setOnClickListener { binding.webview.reload() }

        binding.urlBar.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == android.view.inputmethod.EditorInfo.IME_ACTION_GO ||
                actionId == android.view.inputmethod.EditorInfo.IME_ACTION_DONE
            ) {
                navigateTo(binding.urlBar.text.toString())
                true
            } else false
        }

        binding.videoBanner.setOnClickListener {
            showVideoSelectionDialog()
        }
    }

    private fun navigateTo(input: String) {
        val url = if (!input.startsWith("http://") && !input.startsWith("https://")) {
            "https://$input"
        } else input
        binding.webview.loadUrl(url)
        binding.urlBar.setText(url)
    }

    // --- Video detection ---

    private fun detectVideos(view: WebView) {
        view.evaluateJavascript(VIDEO_DETECT_JS) { result ->
            if (result.isNullOrEmpty() || result == "null" || result == "[]") return@evaluateJavascript
            try {
                val arr = JSONArray(result)
                for (i in 0 until arr.length()) {
                    val u = arr.optString(i)
                    if (u.isNotEmpty() && !videoUrls.contains(u)) videoUrls.add(u)
                }
                if (videoUrls.isNotEmpty()) {
                    binding.videoBanner.visibility = View.VISIBLE
                    binding.videoBannerText.text =
                        getString(R.string.videos_detected, videoUrls.size)
                }
            } catch (_: JSONException) {
            }
        }
    }

    private fun showVideoSelectionDialog() {
        if (videoUrls.isEmpty()) return
        val items = videoUrls.mapIndexed { i, url ->
            "${i + 1}. ${url.take(60)}"
        }.toTypedArray()

        AlertDialog.Builder(this)
            .setTitle(R.string.select_video)
            .setItems(items) { _, which ->
                promptCompressVideo(videoUrls[which])
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    // --- Compression flow ---

    private fun promptCompressVideo(url: String) {
        AlertDialog.Builder(this)
            .setTitle(R.string.compress_video)
            .setMessage(R.string.compress_video_message)
            .setPositiveButton(R.string.compress_and_play) { _, _ ->
                startCompression(url)
            }
            .setNegativeButton(R.string.play_original) { _, _ ->
                VideoPlayerActivity.start(this, url, 0, 0)
            }
            .setNeutralButton(R.string.cancel, null)
            .show()
    }

    private fun startCompression(url: String) {
        binding.statusText.text = getString(R.string.status_downloading)
        binding.progressBar.visibility = View.VISIBLE

        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val result = compressor.compress(url)

                withContext(Dispatchers.Main) {
                    binding.progressBar.visibility = View.GONE
                    val origMb = result.originalSize / (1024.0 * 1024.0)
                    val compMb = result.compressedSize / (1024.0 * 1024.0)
                    val saved = if (result.originalSize > 0) {
                        ((1.0 - result.compressedSize.toDouble() / result.originalSize) * 100).toInt()
                    } else 0

                    binding.statusText.text = getString(R.string.status_saved, saved)
                    VideoPlayerActivity.start(
                        this@MainActivity,
                        result.compressedFile.absolutePath,
                        result.originalSize,
                        result.compressedSize
                    )
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    binding.progressBar.visibility = View.GONE
                    binding.statusText.setText(R.string.status_failed)
                    Toast.makeText(
                        this@MainActivity,
                        R.string.compress_failed,
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
        }
    }

    override fun onBackPressed() {
        if (binding.webview.canGoBack()) binding.webview.goBack()
        else super.onBackPressed()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        binding.webview.saveState(outState)
    }

    override fun onRestoreInstanceState(savedInstanceState: Bundle) {
        super.onRestoreInstanceState(savedInstanceState)
        binding.webview.restoreState(savedInstanceState)
    }
}
