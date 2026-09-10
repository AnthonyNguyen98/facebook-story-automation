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
        val isVideo = media.mimeType.startsWith("video/")
        val safeName = "MEGAS_${System.currentTimeMillis()}_${media.fileName.replace(Regex("[^A-Za-z0-9._-]"), "_")}"

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
            context.contentResolver.openOutputStream(uri)?.use { output ->
                media.file.inputStream().use { input -> input.copyTo(output) }
            } ?: error("MEDIASTORE_OUTPUT_FAILED")
            values.clear()
            values.put(MediaStore.MediaColumns.IS_PENDING, 0)
            context.contentResolver.update(uri, values, null, null)
            media.file.delete()
            return uri
        }

        @Suppress("DEPRECATION")
        val base = Environment.getExternalStoragePublicDirectory(
            if (isVideo) Environment.DIRECTORY_MOVIES else Environment.DIRECTORY_PICTURES
        )
        val dir = File(base, "MEGAS_Stories").apply { mkdirs() }
        val target = File(dir, safeName)
        media.file.inputStream().use { input ->
            FileOutputStream(target).use { output -> input.copyTo(output) }
        }
        media.file.delete()
        MediaScannerConnection.scanFile(context, arrayOf(target.absolutePath), arrayOf(media.mimeType), null)
        return Uri.fromFile(target)
    }
}
