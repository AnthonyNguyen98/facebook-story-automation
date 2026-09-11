package vn.megas.storycompanion

import android.accessibilityservice.AccessibilityService
import android.graphics.Rect
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.util.ArrayDeque

class StoryAccessibilityService : AccessibilityService() {
    private val createStoryTerms = listOf("Tạo tin", "Create story", "Tạo story")
    private val photoVideoTerms = listOf(
        "Ảnh/Video", "Ảnh và video", "Photo/video", "Photo and video", "Thêm ảnh", "Add photo"
    )
    private val galleryTerms = listOf("Gần đây", "Recent", "Thư viện", "Gallery")

    override fun onServiceConnected() {
        super.onServiceConnected()
        Prefs.status(this, "Accessibility Pilot đã bật — không có quyền bấm Publish")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.packageName?.toString() != "com.facebook.pages.app") return
        val jobId = Prefs.currentJob(this)
        if (jobId.isBlank()) return
        val root = rootInActiveWindow ?: return
        saveUiDiagnostic(root)

        val prefs = Prefs.store(this)
        when (prefs.getString("automation_stage", "OPEN_META") ?: "OPEN_META") {
            "OPEN_META" -> {
                when (val count = countExact(root, createStoryTerms)) {
                    1 -> {
                        if (clickUniqueExact(root, createStoryTerms)) {
                            prefs.edit().putString("automation_stage", "AFTER_CREATE").commit()
                            Prefs.status(this, "Pilot: đã vào Tạo tin")
                        }
                    }
                    0 -> Prefs.status(this, "Pilot: chờ đúng nút Tạo tin — diagnostic đã lưu")
                    else -> Prefs.status(this, "Pilot STOP: có $count nút Tạo tin phù hợp, không click")
                }
            }

            "AFTER_CREATE" -> {
                val galleryVisible = countExact(root, galleryTerms) > 0
                if (galleryVisible) {
                    finishPilotAtMediaPicker(jobId)
                    return
                }
                when (val count = countExact(root, photoVideoTerms)) {
                    1 -> {
                        if (clickUniqueExact(root, photoVideoTerms)) {
                            prefs.edit().putString("automation_stage", "MEDIA_PICKER").commit()
                            Prefs.status(this, "Pilot: đã mở thư viện media — chờ diagnostic")
                        }
                    }
                    0 -> Prefs.status(this, "Pilot: chưa nhận diện nút Ảnh/Video — diagnostic đã lưu")
                    else -> Prefs.status(this, "Pilot STOP: có $count nút Ảnh/Video phù hợp, không click")
                }
            }

            "MEDIA_PICKER" -> finishPilotAtMediaPicker(jobId)

            // If reporting failed because the network was down, the stopped state is
            // allowed to retry the same idempotent DRY_RUN_READY callback. It never clicks UI.
            "PILOT_STOPPED_AT_MEDIA_PICKER" -> reportPilotResult(jobId)

            // No other states are executable in the pilot APK. In particular there is no
            // Sticker, Link form, media-selection, or Publish action code in this build.
            else -> Prefs.status(this, "Pilot STOP: stage ngoài whitelist, không thao tác")
        }
    }

    private fun finishPilotAtMediaPicker(jobId: String) {
        val prefs = Prefs.store(this)
        prefs.edit()
            .putString("automation_stage", "PILOT_STOPPED_AT_MEDIA_PICKER")
            .commit()
        Prefs.status(this, "PILOT OK — dừng tại thư viện, không chọn media, không chạm Publish")
        reportPilotResult(jobId)
    }

    private fun reportPilotResult(jobId: String) {
        val prefs = Prefs.store(this)
        if (prefs.getBoolean("pilot_report_sent", false)) return
        val claimToken = Prefs.claimToken(this)
        if (claimToken.isBlank()) {
            Prefs.status(this, "Pilot STOP: thiếu claim token, dùng Recovery trong app")
            return
        }

        // Synchronous commit acts as a local single-flight guard against rapid Accessibility events.
        if (!prefs.edit().putBoolean("pilot_report_sent", true).commit()) {
            Prefs.status(this, "Pilot STOP: không khóa được report local")
            return
        }
        val diagnostic = prefs.getString("last_ui_dump", "").orEmpty().take(900)
        Thread {
            try {
                ApiClient(this).result(
                    jobId = jobId,
                    claimToken = claimToken,
                    state = "DRY_RUN_READY",
                    note = "PILOT_STOP_MEDIA_PICKER | $diagnostic",
                )
                // Keep diagnostic, but clear the lease/job so the phone cannot accidentally continue.
                Prefs.clearJob(this)
                Prefs.status(this, "PILOT hoàn tất — hãy Copy UI diagnostic gửi để map bước tiếp theo")
            } catch (e: Exception) {
                prefs.edit().putBoolean("pilot_report_sent", false).apply()
                Prefs.status(this, "Pilot đã dừng; chờ event để retry report: ${e.message}")
            }
        }.start()
    }

    private fun nodeMatchesExact(node: AccessibilityNodeInfo, terms: Collection<String>): Boolean {
        val klass = node.className?.toString().orEmpty()
        if (klass.contains("EditText", ignoreCase = true)) return false
        return UiMatcher.exactEither(node.text, node.contentDescription, terms)
    }

    private fun exactNodes(root: AccessibilityNodeInfo, terms: Collection<String>): List<AccessibilityNodeInfo> {
        val out = mutableListOf<AccessibilityNodeInfo>()
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        var seen = 0
        while (queue.isNotEmpty() && seen < 800) {
            val node = queue.removeFirst()
            seen++
            if (nodeMatchesExact(node, terms)) out.add(node)
            for (i in 0 until node.childCount) node.getChild(i)?.let { queue.add(it) }
        }
        return out
    }

    private fun countExact(root: AccessibilityNodeInfo, terms: Collection<String>): Int =
        exactNodes(root, terms).size

    private fun clickUniqueExact(root: AccessibilityNodeInfo, terms: Collection<String>): Boolean {
        val matches = exactNodes(root, terms)
        if (matches.size != 1) return false
        return clickNode(matches.single())
    }

    private fun clickNode(node: AccessibilityNodeInfo): Boolean {
        var current: AccessibilityNodeInfo? = node
        var depth = 0
        while (current != null && depth < 4) {
            if (current.isClickable && current.isEnabled) {
                return current.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            }
            current = current.parent
            depth++
        }
        return false
    }

    private fun diagnosticLabel(value: CharSequence?): String {
        val raw = value?.toString()?.trim().orEmpty().replace(Regex("\\s+"), " ")
        if (raw.isBlank()) return ""
        if (Regex("https?://", RegexOption.IGNORE_CASE).containsMatchIn(raw)) return "[url-redacted]"
        if (Regex("[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}", RegexOption.IGNORE_CASE).containsMatchIn(raw)) {
            return "[email-redacted]"
        }
        return raw.take(60)
    }

    private fun saveUiDiagnostic(root: AccessibilityNodeInfo) {
        val lines = linkedSetOf<String>()
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        var seen = 0
        while (queue.isNotEmpty() && seen < 700 && lines.size < 120) {
            val node = queue.removeFirst()
            seen++
            val klass = node.className?.toString().orEmpty()
            val isEditor = node.isEditable || klass.contains("EditText", ignoreCase = true)
            if (!isEditor && (node.isClickable || klass.contains("Button", ignoreCase = true))) {
                val text = diagnosticLabel(node.text)
                val desc = diagnosticLabel(node.contentDescription)
                val id = node.viewIdResourceName.orEmpty().take(100)
                val bounds = Rect().also { node.getBoundsInScreen(it) }
                if (text.isNotBlank() || desc.isNotBlank() || id.isNotBlank()) {
                    lines.add("class=${klass.substringAfterLast('.').take(40)};text=$text;desc=$desc;id=$id;click=${node.isClickable};bounds=$bounds")
                }
            }
            for (i in 0 until node.childCount) node.getChild(i)?.let { queue.add(it) }
        }
        Prefs.store(this).edit().putString("last_ui_dump", lines.joinToString("\n").take(12000)).apply()
    }

    override fun onInterrupt() {
        Prefs.status(this, "Accessibility Pilot bị tạm ngắt")
    }
}
