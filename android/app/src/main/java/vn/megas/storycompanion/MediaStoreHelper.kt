package vn.megas.storycompanion

import android.content.ContentValues
import android.content.Context
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import java.io.File
import java.io.FileOutputStream

object MediaStoreHelper {
    fun save(context: Context, media: ApiClient.DownloadedMedia): Uri {
        if (!media.file.exists() || media.file.length() <= 0L) error("SOURCE_MEDIA_EMPTY")
        val isVideo = media.mimeType.startsWith("video/")
        val isImage = media.mimeType.startsWith("image/")
        if (!isVideo && !isImage) error("UNSUPPORTED_MEDIA_TYPE")
        val sourceSize = media.file.length()
        if (sourceSize > ApiClient.MAX_MEDIA_BYTES) error("SOURCE_MEDIA_TOO_LARGE")

        val safeOriginal = media.fileName.replace(Regex("[^A-Za-z0-9._-]"), "_").take(150)
        val safeName = "MEGAS_${System.currentTimeMillis()}_${safeOriginal.ifBlank { if (isVideo) "story.mp4" else "story.jpg" }}"

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val collection = if (isVideo) {
                MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            } else {
                MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            }
            val relative = if (isVideo) "Movies/MEGAS_Stories" else "Pictures/MEGAS_Stories"
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, safeName)
                put(MediaStore.MediaColumns.MIME_TYPE, media.mimeType)
                put(MediaStore.MediaColumns.RELATIVE_PATH, relative)
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val uri = context.contentResolver.insert(collection, values)
                ?: error("MEDIASTORE_INSERT_FAILED")
            try {
                val output = context.contentResolver.openOutputStream(uri)
                    ?: error("MEDIASTORE_OUTPUT_FAILED")
                output.use { out ->
                    media.file.inputStream().use { input -> input.copyTo(out) }
                }
                val done = ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }
                context.contentResolver.update(uri, done, null, null)
                media.file.delete()
                return uri
            } catch (e: Exception) {
                context.contentResolver.delete(uri, null, null)
                throw e
            }
        }

        @Suppress("DEPRECATION")
        val base = Environment.getExternalStoragePublicDirectory(
            if (isVideo) Environment.DIRECTORY_MOVIES else Environment.DIRECTORY_PICTURES
        )
        val dir = File(base, "MEGAS_Stories")
        if (!dir.exists() && !dir.mkdirs()) error("MEDIA_DIRECTORY_CREATE_FAILED")
        val target = File(dir, safeName)
        try {
            media.file.inputStream().use { input ->
                FileOutputStream(target).use { output -> input.copyTo(output) }
            }
            if (target.length() != sourceSize) {
                target.delete()
                error("MEDIA_COPY_SIZE_MISMATCH")
            }
            media.file.delete()
            MediaScannerConnection.scanFile(
                context,
                arrayOf(target.absolutePath),
                arrayOf(media.mimeType),
                null,
            )
            return Uri.fromFile(target)
        } catch (e: Exception) {
            target.delete()
            throw e
        }
    }
}
