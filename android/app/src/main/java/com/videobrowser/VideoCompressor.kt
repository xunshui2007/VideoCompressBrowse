package com.videobrowser

import android.content.Context
import android.util.Log
import com.arthenica.ffmpegkit.FFmpegKit
import com.arthenica.ffmpegkit.ReturnCode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

data class CompressResult(
    val compressedFile: File,
    val originalSize: Long,
    val compressedSize: Long
)

class VideoCompressor(private val context: Context) {

    private val cacheDir: File
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    data class CacheEntry(
        val inputFile: File,
        val outputFile: File
    )

    init {
        cacheDir = File(context.cacheDir, "video_cache").also { it.mkdirs() }
    }

    suspend fun compress(url: String): CompressResult = withContext(Dispatchers.IO) {
        val urlHash = urlHash(url)
        val inputFile = File(cacheDir, "${urlHash}_input")
        val outputFile = File(cacheDir, "${urlHash}_compressed.mp4")

        // Check cache
        if (outputFile.exists() && outputFile.length() > 1024) {
            val origSize = inputFile.takeIf { it.exists() }?.length() ?: 0L
            return@withContext CompressResult(outputFile, origSize, outputFile.length())
        }

        // Step 1: download
        download(url, inputFile)
        val origSize = inputFile.length()

        // Step 2: transcode with FFmpeg
        val cmd = listOf(
            "-i", inputFile.absolutePath,
            "-vf", "fps=20",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-c:a", "copy",
            "-movflags", "frag_keyframe+empty_moov",
            "-y", outputFile.absolutePath
        )

        val session = FFmpegKit.execute(cmd.toTypedArray())

        if (ReturnCode.isSuccess(session.returnCode) && outputFile.exists() && outputFile.length() > 0) {
            val compSize = outputFile.length()
            Log.i(TAG, "Compressed ${origSize / 1024}KB -> ${compSize / 1024}KB " +
                    "(${(100 - compSize * 100 / origSize)}% saved)")
            CompressResult(outputFile, origSize, compSize)
        } else {
            Log.w(TAG, "FFmpeg failed, using original")
            // Fall back to original file
            outputFile.delete()
            inputFile.copyTo(outputFile, overwrite = true)
            CompressResult(outputFile, origSize, outputFile.length())
        }
    }

    private fun download(url: String, target: File) {
        val request = Request.Builder().url(url)
            .header("User-Agent", "Mozilla/5.0 (Android 16; Mobile) AppleWebKit/537.36 VideoCompressBrowser/1.0")
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw RuntimeException("Download failed: HTTP ${response.code}")
            }
            response.body?.byteStream()?.use { input ->
                FileOutputStream(target).use { output ->
                    input.copyTo(output)
                }
            }
        }
    }

    private fun urlHash(url: String): String {
        val digest = MessageDigest.getInstance("MD5").digest(url.toByteArray())
        return digest.joinToString("") { "%02x".format(it) }
    }

    fun clearCache() {
        cacheDir.listFiles()?.forEach { it.delete() }
    }

    companion object {
        private const val TAG = "VideoCompressor"
    }
}
