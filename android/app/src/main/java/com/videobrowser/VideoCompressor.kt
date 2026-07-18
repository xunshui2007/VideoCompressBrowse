package com.videobrowser

import android.content.Context
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.nio.ByteBuffer

data class CompressResult(
    val compressedFile: File,
    val originalSize: Long,
    val compressedSize: Long
)

class VideoCompressor(private val context: Context) {

    private val cacheDir: File
    private val TARGET_FPS = 20
    private val FRAME_INTERVAL_US = 1_000_000L / TARGET_FPS

    init {
        cacheDir = File(context.cacheDir, "video_cache").also { it.mkdirs() }
    }

    suspend fun compress(url: String): CompressResult = withContext(Dispatchers.IO) {
        val urlHash = urlHash(url)
        val inputFile = File(cacheDir, "${urlHash}_input")
        val outputFile = File(cacheDir, "${urlHash}_compressed.mp4")

        if (outputFile.exists() && outputFile.length() > 1024) {
            val origSize = inputFile.takeIf { it.exists() }?.length() ?: 0L
            return@withContext CompressResult(outputFile, origSize, outputFile.length())
        }

        download(url, inputFile)
        val origSize = inputFile.length()
        transcode(inputFile, outputFile)
        val compSize = outputFile.length()
        CompressResult(outputFile, origSize, compSize)
    }

    private fun transcode(inputFile: File, outputFile: File) {
        val extractor = MediaExtractor()
        extractor.setDataSource(inputFile.absolutePath)

        val videoTrackIdx = findTrack(extractor, "video/")
        val audioTrackIdx = findTrack(extractor, "audio/")

        if (videoTrackIdx < 0) {
            // No video track, just copy
            inputFile.copyTo(outputFile, overwrite = true)
            extractor.release()
            return
        }

        val videoFormat = extractor.getTrackFormat(videoTrackIdx)
        val srcFps = estimateFps(videoFormat)

        val muxer = MediaMuxer(outputFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)

        var videoMuxerTrack = -1
        var audioMuxerTrack = -1

        val (decoder, encoder, inputSurface) = setupCodecs(videoFormat)

        decoder.start()
        encoder.start()

        extractor.selectTrack(videoTrackIdx)

        val audioExtractor: MediaExtractor? = if (audioTrackIdx >= 0) {
            val ae = MediaExtractor().apply { setDataSource(inputFile.absolutePath) }
            ae.selectTrack(audioTrackIdx)
            ae
        } else null

        val audioFormat = audioTrackIdx.let { if (it >= 0) extractor.getTrackFormat(it) else null }
        var audioDecoder: MediaCodec? = null
        var audioEncoder: MediaCodec? = null
        var audioInputSurface: android.view.Surface? = null

        val bufferInfo = MediaCodec.BufferInfo()
        var sawInputEOS = false
        var sawOutputEOS = false
        var muxerStarted = false
        var outputFrameCount = 0

        while (!sawOutputEOS) {
            // Feed extractor to decoder
            if (!sawInputEOS) {
                val inIdx = decoder.dequeueInputBuffer(10_000)
                if (inIdx >= 0) {
                    val buf = decoder.getInputBuffer(inIdx) ?: continue
                    val chunkSize = extractor.readSampleData(buf, 0)
                    if (chunkSize < 0) {
                        decoder.queueInputBuffer(inIdx, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                        sawInputEOS = true
                    } else {
                        val pts = extractor.sampleTime
                        decoder.queueInputBuffer(inIdx, 0, chunkSize, pts, extractor.sampleFlags)
                        extractor.advance()
                    }
                }
            }

            // Get decoder output
            val outIdx = decoder.dequeueOutputBuffer(bufferInfo, 10_000)
            when {
                outIdx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                    if (!muxerStarted && videoMuxerTrack < 0) {
                        videoMuxerTrack = muxer.addTrack(encoder.outputFormat)
                    }
                }
                outIdx == MediaCodec.INFO_TRY_AGAIN_LATER -> {}
                outIdx >= 0 -> {
                    val shouldRender = shouldKeepFrame(bufferInfo.presentationTimeUs, outputFrameCount)
                    decoder.releaseOutputBuffer(outIdx, shouldRender)

                    if (shouldRender) outputFrameCount++

                    // Poll encoder output
                    if (muxerStarted) {
                        drainEncoder(encoder, muxer, videoMuxerTrack, bufferInfo, false)
                    }
                }
            }

            // Start muxer after encoder format is known
            if (!muxerStarted && videoMuxerTrack >= 0) {
                muxer.start()
                muxerStarted = true
            }

            // Handle EOS
            if ((bufferInfo.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) {
                sawOutputEOS = true
            }
        }

        drainEncoder(encoder, muxer, videoMuxerTrack, bufferInfo, true)

        // Audio passthrough not implemented in v1
        audioExtractor?.release()

        decoder.stop()
        decoder.release()
        encoder.stop()
        encoder.release()
        extractor.release()
        muxer.stop()
        muxer.release()
    }

    private fun setupCodecs(inputFormat: MediaFormat): Triple<MediaCodec, MediaCodec, android.view.Surface> {
        val mime = inputFormat.getString(MediaFormat.KEY_MIME)!!

        val decoder = MediaCodec.createDecoderByType(mime)
        decoder.configure(inputFormat, null, null, 0)

        val width = inputFormat.getInteger(MediaFormat.KEY_WIDTH)
        val height = inputFormat.getInteger(MediaFormat.KEY_HEIGHT)
        val bitrate = estimateBitrate(width, height)

        val outputFormat = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, width, height).apply {
            setInteger(MediaFormat.KEY_BIT_RATE, bitrate)
            setInteger(MediaFormat.KEY_FRAME_RATE, TARGET_FPS)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
        }

        val encoder = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
        encoder.configure(outputFormat, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        val inputSurface = encoder.createInputSurface()

        return Triple(decoder, encoder, inputSurface)
    }

    private fun shouldKeepFrame(ptsUs: Long, frameCount: Int): Boolean {
        // Adjust frame rate by calculating expected output frame position
        val expectedFrame = ptsUs / FRAME_INTERVAL_US
        return expectedFrame > frameCount - 1
    }

    private fun drainEncoder(
        encoder: MediaCodec,
        muxer: MediaMuxer,
        track: Int,
        bufferInfo: MediaCodec.BufferInfo,
        endOfStream: Boolean
    ) {
        if (endOfStream) {
            encoder.signalEndOfInputStream()
        }

        while (true) {
            val outIdx = encoder.dequeueOutputBuffer(bufferInfo, 10_000)
            when {
                outIdx == MediaCodec.INFO_TRY_AGAIN_LATER -> {
                    if (!endOfStream) break else continue
                }
                outIdx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> continue
                outIdx >= 0 -> {
                    val outBuf = encoder.getOutputBuffer(outIdx) ?: continue
                    if (bufferInfo.size > 0 && track >= 0) {
                        outBuf.position(bufferInfo.offset)
                        outBuf.limit(bufferInfo.offset + bufferInfo.size)
                        muxer.writeSampleData(track, outBuf, bufferInfo)
                    }
                    encoder.releaseOutputBuffer(outIdx, false)
                    if ((bufferInfo.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) {
                        break
                    }
                }
            }
        }
    }

    private fun findTrack(extractor: MediaExtractor, prefix: String): Int {
        for (i in 0 until extractor.trackCount) {
            val mime = extractor.getTrackFormat(i).getString(MediaFormat.KEY_MIME) ?: continue
            if (mime.startsWith(prefix)) return i
        }
        return -1
    }

    private fun estimateFps(format: MediaFormat): Int {
        val fps = if (format.containsKey(MediaFormat.KEY_FRAME_RATE)) {
            format.getInteger(MediaFormat.KEY_FRAME_RATE)
        } else 30
        return if (fps <= 0) 30 else fps
    }

    private fun estimateBitrate(width: Int, height: Int): Int {
        val pixels = width * height
        return when {
            pixels > 1280 * 720 -> 2_000_000
            pixels > 854 * 480 -> 1_000_000
            else -> 500_000
        }
    }

    private fun urlHash(url: String): String {
        val digest = java.security.MessageDigest.getInstance("MD5").digest(url.toByteArray())
        return digest.joinToString("") { "%02x".format(it) }
    }

    private fun download(url: String, target: File) {
        val client = okhttp3.OkHttpClient.Builder()
            .connectTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
            .readTimeout(120, java.util.concurrent.TimeUnit.SECONDS)
            .followRedirects(true)
            .build()

        val request = okhttp3.Request.Builder().url(url)
            .header("User-Agent", "Mozilla/5.0 (Android 16; Mobile) AppleWebKit/537.36 VideoCompressBrowser/1.0")
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw RuntimeException("Download failed: HTTP ${response.code}")
            }
            response.body?.byteStream()?.use { input ->
                java.io.FileOutputStream(target).use { output ->
                    input.copyTo(output)
                }
            }
        }
    }

    fun clearCache() {
        cacheDir.listFiles()?.forEach { it.delete() }
    }

    companion object {
        private const val TAG = "VideoCompressor"
    }
}
