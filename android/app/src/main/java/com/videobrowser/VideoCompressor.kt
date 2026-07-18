package com.videobrowser

import android.content.Context
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest

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
        val urlHash = md5(url)
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
        if (videoTrackIdx < 0) {
            inputFile.copyTo(outputFile, overwrite = true)
            extractor.release()
            return
        }

        val videoFormat = extractor.getTrackFormat(videoTrackIdx)
        val width = videoFormat.getInteger(MediaFormat.KEY_WIDTH)
        val height = videoFormat.getInteger(MediaFormat.KEY_HEIGHT)

        val muxer = MediaMuxer(outputFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)

        val decoder = MediaCodec.createDecoderByType(videoFormat.getString(MediaFormat.KEY_MIME)!!)
        val encoder = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)

        val outputFormat = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, width, height).apply {
            setInteger(MediaFormat.KEY_BIT_RATE, estimateBitrate(width, height))
            setInteger(MediaFormat.KEY_FRAME_RATE, TARGET_FPS)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
        }

        encoder.configure(outputFormat, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        val encoderSurface = encoder.createInputSurface()

        decoder.configure(videoFormat, encoderSurface, null, 0)

        decoder.start()
        encoder.start()
        extractor.selectTrack(videoTrackIdx)

        val decBufferInfo = MediaCodec.BufferInfo()
        val encBufferInfo = MediaCodec.BufferInfo()

        var decoderInputDone = false
        var decoderDone = false
        var videoMuxerTrack = -1
        var muxerStarted = false
        var lastKeptPtsUs = Long.MIN_VALUE
        var renderFrameCount = 0

        while (!decoderDone) {
            if (!decoderInputDone) {
                val inIdx = decoder.dequeueInputBuffer(10_000)
                if (inIdx >= 0) {
                    val buf = decoder.getInputBuffer(inIdx)!!
                    val chunkSize = extractor.readSampleData(buf, 0)
                    if (chunkSize < 0) {
                        decoder.queueInputBuffer(inIdx, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                        decoderInputDone = true
                    } else {
                        decoder.queueInputBuffer(inIdx, 0, chunkSize, extractor.sampleTime, extractor.sampleFlags)
                        extractor.advance()
                    }
                }
            }

            val outIdx = decoder.dequeueOutputBuffer(decBufferInfo, 10_000)
            when {
                outIdx == MediaCodec.INFO_TRY_AGAIN_LATER -> {}
                outIdx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {}
                outIdx >= 0 -> {
                    val eos = (decBufferInfo.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0
                    if (eos) decoderDone = true
                    val pts = decBufferInfo.presentationTimeUs
                    val shouldRender = !eos && (pts >= lastKeptPtsUs + FRAME_INTERVAL_US)
                    if (shouldRender) {
                        lastKeptPtsUs = pts
                        val renderTimeNs = renderFrameCount * FRAME_INTERVAL_US * 1000L
                        decoder.releaseOutputBuffer(outIdx, true, renderTimeNs)
                        renderFrameCount++
                    } else {
                        decoder.releaseOutputBuffer(outIdx, false)
                    }
                }
            }

            while (true) {
                val encIdx = encoder.dequeueOutputBuffer(encBufferInfo, 0)
                if (encIdx == MediaCodec.INFO_TRY_AGAIN_LATER) break
                when (encIdx) {
                    MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        videoMuxerTrack = muxer.addTrack(encoder.outputFormat)
                    }
                    encIdx >= 0 -> {
                        val encBuf = encoder.getOutputBuffer(encIdx)!!
                        if (encBufferInfo.size > 0 && muxerStarted) {
                            encBuf.position(encBufferInfo.offset)
                            encBuf.limit(encBufferInfo.offset + encBufferInfo.size)
                            muxer.writeSampleData(videoMuxerTrack, encBuf, encBufferInfo)
                        }
                        encoder.releaseOutputBuffer(encIdx, false)
                    }
                }
            }

            if (!muxerStarted && videoMuxerTrack >= 0) {
                muxer.start()
                muxerStarted = true
            }
        }

        encoder.signalEndOfInputStream()

        while (true) {
            val encIdx = encoder.dequeueOutputBuffer(encBufferInfo, 50_000)
            when {
                encIdx == MediaCodec.INFO_TRY_AGAIN_LATER -> break
                encIdx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                    if (videoMuxerTrack < 0) {
                        videoMuxerTrack = muxer.addTrack(encoder.outputFormat)
                        if (!muxerStarted) {
                            muxer.start()
                            muxerStarted = true
                        }
                    }
                }
                encIdx >= 0 -> {
                    val encBuf = encoder.getOutputBuffer(encIdx)!!
                    if (encBufferInfo.size > 0 && muxerStarted) {
                        encBuf.position(encBufferInfo.offset)
                        encBuf.limit(encBufferInfo.offset + encBufferInfo.size)
                        muxer.writeSampleData(videoMuxerTrack, encBuf, encBufferInfo)
                    }
                    encoder.releaseOutputBuffer(encIdx, false)
                    if ((encBufferInfo.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) break
                }
            }
        }

        decoder.stop()
        decoder.release()
        encoder.stop()
        encoder.release()
        extractor.release()
        if (muxerStarted) {
            muxer.stop()
        }
        muxer.release()
    }

    private fun findTrack(extractor: MediaExtractor, prefix: String): Int {
        for (i in 0 until extractor.trackCount) {
            val mime = extractor.getTrackFormat(i).getString(MediaFormat.KEY_MIME) ?: continue
            if (mime.startsWith(prefix)) return i
        }
        return -1
    }

    private fun estimateBitrate(width: Int, height: Int): Int {
        val pixels = width * height
        return when {
            pixels > 1280 * 720 -> 2_000_000
            pixels > 854 * 480 -> 1_000_000
            else -> 500_000
        }
    }

    private fun md5(s: String): String {
        val digest = MessageDigest.getInstance("MD5").digest(s.toByteArray())
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
