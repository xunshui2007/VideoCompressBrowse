package com.videobrowser

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.os.Bundle
import android.os.Handler
import android.os.Looper
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
    private var isPrivate = false

    companion object {
        private val VIDEO_EXT = Regex(
            "\\.(mp4|webm|m3u8|ts|mkv|avi|mov)(\\?.*)?$",
            RegexOption.IGNORE_CASE
        )
    }

    private val VIDEO_DETECT_JS = """
        (function() {
            var urls = [];
            var seen = {};
            function scan() {
                // <video> elements
                var vs = document.querySelectorAll('video');
                for (var i = 0; i < vs.length; i++) {
                    if (vs[i].src && !seen[vs[i].src]) { seen[vs[i].src] = 1; urls.push(vs[i].src); }
                    if (vs[i].poster && !seen[vs[i].poster]) { seen[vs[i].poster] = 1; urls.push(vs[i].poster); }
                    var ss = vs[i].querySelectorAll('source');
                    for (var j = 0; j < ss.length; j++) {
                        if (ss[j].src && !seen[ss[j].src]) { seen[ss[j].src] = 1; urls.push(ss[j].src); }
                    }
                }
                // <a> links to video files
                var exts = /\.(mp4|webm|m3u8|ts|mkv|avi|mov)(\?.*)?$/i;
                var as = document.querySelectorAll('a[href]');
                for (var i = 0; i < as.length; i++) {
                    if (exts.test(as[i].href) && !seen[as[i].href]) { seen[as[i].href] = 1; urls.push(as[i].href); }
                }
                // data-* attributes with video URLs
                var all = document.querySelectorAll('[data-video],[data-src],[data-url]');
                for (var i = 0; i < all.length; i++) {
                    var val = all[i].getAttribute('data-video') || all[i].getAttribute('data-src') || all[i].getAttribute('data-url');
                    if (val && exts.test(val) && !seen[val]) { seen[val] = 1; urls.push(val); }
                }
                return urls;
            }
            return scan();
        })();
    """.trimIndent()

    private var videoPollHandler: Handler? = null
    private var videoPollRunnable: Runnable? = null

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
                stopVideoPolling()
            }

            override fun onPageFinished(view: WebView, url: String) {
                binding.statusText.setText(R.string.status_compression_ready)
                detectVideos(view)
                startVideoPolling(view)
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

        binding.btnPrivate.setOnClickListener { togglePrivateMode() }

        binding.videoBanner.setOnClickListener {
            showVideoSelectionDialog()
        }

        updatePrivateUi()
    }

    private fun navigateTo(input: String) {
        val url = if (!input.startsWith("http://") && !input.startsWith("https://")) {
            "https://$input"
        } else input
        binding.webview.loadUrl(url)
        binding.urlBar.setText(url)
    }

    // --- Private mode ---

    private fun togglePrivateMode() {
        isPrivate = !isPrivate
        updatePrivateUi()
        if (isPrivate) {
            binding.webview.settings.cacheMode = WebSettings.LOAD_NO_CACHE
            binding.webview.clearCache(true)
            binding.webview.clearFormData()
            android.webkit.CookieManager.getInstance().removeAllCookies(null)
            binding.statusText.setText(R.string.status_private)
        } else {
            binding.webview.settings.cacheMode = WebSettings.LOAD_DEFAULT
            binding.statusText.setText(R.string.status_compression_ready)
        }
    }

    private fun updatePrivateUi() {
        if (isPrivate) {
            binding.toolbar.setBackgroundColor(getColor(R.color.private_toolbar_bg))
            binding.statusText.setBackgroundColor(getColor(R.color.private_bg))
            binding.statusText.setTextColor(getColor(android.R.color.white))
            binding.btnPrivate.setColorFilter(getColor(android.R.color.holo_orange_dark))
            binding.btnPrivate.setAlpha(1.0f)
        } else {
            binding.toolbar.setBackgroundColor(getColor(R.color.toolbar_bg))
            binding.statusText.setBackgroundColor(getColor(R.color.status_bg))
            binding.statusText.setTextColor(getColor(android.R.color.primary_text_dark))
            binding.btnPrivate.clearColorFilter()
            binding.btnPrivate.setAlpha(0.5f)
        }
    }

    // --- Video detection ---

    private fun detectVideos(view: WebView) {
        view.evaluateJavascript(VIDEO_DETECT_JS) { result ->
            if (result.isNullOrEmpty() || result == "null" || result == "[]") return@evaluateJavascript
            try {
                val arr = JSONArray(result)
                var added = false
                for (i in 0 until arr.length()) {
                    val u = arr.optString(i)
                    if (u.isNotEmpty() && !videoUrls.contains(u)) {
                        videoUrls.add(u)
                        added = true
                    }
                }
                if (added) {
                    binding.videoBanner.visibility = View.VISIBLE
                    binding.videoBannerText.text =
                        getString(R.string.videos_detected, videoUrls.size)
                }
            } catch (_: JSONException) {
            }
        }
    }

    private fun startVideoPolling(view: WebView) {
        stopVideoPolling()
        val handler = Handler(Looper.getMainLooper())
        videoPollHandler = handler
        var count = 0
        val runnable = object : Runnable {
            override fun run() {
                if (count >= 8) return
                count++
                detectVideos(view)
                handler.postDelayed(this, 2000)
            }
        }
        videoPollRunnable = runnable
        handler.postDelayed(runnable, 2000)
    }

    private fun stopVideoPolling() {
        videoPollRunnable?.let { videoPollHandler?.removeCallbacks(it) }
        videoPollRunnable = null
        videoPollHandler = null
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
        binding.progressBar.visibility = View.VISIBLE
        binding.progressBar.max = 100

        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val result = compressor.compress(url, object : ProgressCallback {
                    override fun onProgress(bytesRead: Long, totalBytes: Long) {
                        val pct = ((bytesRead.toDouble() / totalBytes) * 100).toInt()
                        binding.root.post {
                            binding.statusText.text = "下载中 $pct%"
                            binding.progressBar.progress = pct
                        }
                    }
                    override fun onStage(stage: String) {
                        binding.root.post { binding.statusText.text = stage }
                    }
                })

                withContext(Dispatchers.Main) {
                    binding.progressBar.visibility = View.GONE
                    val origMb = "%.1f".format(result.originalSize / (1024.0 * 1024.0))
                    val compMb = "%.1f".format(result.compressedSize / (1024.0 * 1024.0))
                    val saved = if (result.originalSize > 0) {
                        ((1.0 - result.compressedSize.toDouble() / result.originalSize) * 100).toInt()
                    } else 0

                    val summary = "原始 ${origMb}MB → 压缩后 ${compMb}MB (节省 $saved%)"
                    binding.statusText.text = summary

                    AlertDialog.Builder(this@MainActivity)
                        .setTitle("压缩完成")
                        .setMessage(summary)
                        .setPositiveButton("播放") { _, _ ->
                            VideoPlayerActivity.start(
                                this@MainActivity,
                                result.compressedFile.absolutePath,
                                result.originalSize,
                                result.compressedSize
                            )
                        }
                        .setNegativeButton("直接播放原视频") { _, _ ->
                            VideoPlayerActivity.start(this@MainActivity, url, 0, 0)
                        }
                        .show()
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    binding.progressBar.visibility = View.GONE
                    binding.statusText.setText(R.string.status_failed)
                    Toast.makeText(
                        this@MainActivity,
                        "压缩失败: ${e.message}",
                        Toast.LENGTH_LONG
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

    override fun onDestroy() {
        super.onDestroy()
        if (isPrivate) {
            binding.webview.clearCache(true)
            binding.webview.clearHistory()
            android.webkit.CookieManager.getInstance().removeAllCookies(null)
        }
    }
}
