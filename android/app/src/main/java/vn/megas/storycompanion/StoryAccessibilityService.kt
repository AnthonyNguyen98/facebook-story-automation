package vn.megas.storycompanion

import android.accessibilityservice.AccessibilityService
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.util.ArrayDeque

class StoryAccessibilityService : AccessibilityService() {
    override fun onServiceConnected() {
        super.onServiceConnected()
        Prefs.status(this, "Accessibility đã bật — chờ Story")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.packageName?.toString() != "com.facebook.pages.app") return
        val jobId = Prefs.currentJob(this)
        if (jobId.isBlank()) return
        val root = rootInActiveWindow ?: return
        saveUiDiagnostic(root)

        val prefs = Prefs.store(this)
        val stage = prefs.getString("automation_stage", "OPEN_META") ?: "OPEN_META"

        // State recovery: if composer controls are already visible, continue from there.
        if (stage in setOf("AFTER_CREATE", "MEDIA_PICKER") && hasAny(root, listOf("Nhãn dán", "Sticker", "Stickers"))) {
            if (clickAny(root, listOf("Nhãn dán", "Sticker", "Stickers"))) {
                prefs.edit().putString("automation_stage", "STICKER_MENU").apply()
                Prefs.status(this, "Đã mở Sticker cho $jobId")
                return
            }
        }

        when (stage) {
            "OPEN_META" -> {
                if (clickAny(root, listOf("Tạo tin", "Create story", "Tạo story"))) {
                    prefs.edit().putString("automation_stage", "AFTER_CREATE").apply()
                    Prefs.status(this, "Đã vào Tạo tin — đang tìm media")
                } else {
                    Prefs.status(this, "Đang chờ nút Tạo tin…")
                }
            }

            "AFTER_CREATE" -> {
                if (clickAny(root, listOf("Ảnh/Video", "Ảnh và video", "Photo/video", "Photo and video", "Thêm ảnh", "Add photo"))) {
                    prefs.edit().putString("automation_stage", "MEDIA_PICKER").apply()
                    Prefs.status(this, "Đã mở thư viện media")
                } else if (hasAny(root, listOf("Gần đây", "Recent", "Thư viện", "Gallery"))) {
                    prefs.edit().putString("automation_stage", "MEDIA_PICKER").apply()
                    Prefs.status(this, "Đã nhận diện thư viện — chờ map thumbnail chính xác")
                } else {
                    Prefs.status(this, "Cần map UI sau màn Tạo tin — diagnostic đã lưu")
                }
            }

            "MEDIA_PICKER" -> {
                // Intentionally no blind thumbnail click in v0.1. The first device test maps
                // the exact gallery node so we never choose the wrong photo/video.
                Prefs.status(this, "Thư viện đã mở — cần map thumbnail trên đúng máy Android")
            }

            "STICKER_MENU" -> {
                if (clickAny(root, listOf("Liên kết", "Link"))) {
                    prefs.edit().putString("automation_stage", "LINK_FORM").apply()
                    Prefs.status(this, "Đã mở Link Sticker")
                } else {
                    Prefs.status(this, "Đang tìm Link Sticker…")
                }
            }

            "LINK_FORM" -> {
                val url = prefs.getString("current_link_url", "") ?: ""
                val linkText = prefs.getString("current_link_text", "") ?: ""
                val editors = editableNodes(root)
                if (editors.isEmpty()) {
                    Prefs.status(this, "Đang chờ ô URL của Link Sticker…")
                    return
                }
                setNodeText(editors[0], url)
                if (editors.size >= 2 && linkText.isNotBlank()) {
                    setNodeText(editors[1], linkText)
                }
                if (clickAny(root, listOf("Xong", "Done", "Thêm", "Add"))) {
                    prefs.edit().putString("automation_stage", "FINAL_COMPOSER").apply()
                    Prefs.status(this, "Đã điền Link Sticker — kiểm tra màn cuối")
                }
            }

            "FINAL_COMPOSER" -> {
                val publishNode = findAny(root, listOf("Chia sẻ tin", "Share story", "Đăng", "Publish"))
                if (publishNode == null) {
                    Prefs.status(this, "Đang chờ nút Publish…")
                    return
                }
                val publishAllowed = prefs.getBoolean("publish_allowed", false)
                if (!publishAllowed) {
                    prefs.edit().putString("automation_stage", "DRY_RUN_READY").apply()
                    Prefs.status(this, "DRY RUN OK — đã dừng trước Publish")
                    reportAndClear(jobId, "DRY_RUN_READY", "Dừng an toàn trước nút Publish")
                } else if (clickNode(publishNode)) {
                    prefs.edit().putString("automation_stage", "PUBLISHING").apply()
                    Prefs.status(this, "Đã bấm Publish — đang chờ xác nhận")
                }
            }

            "PUBLISHING" -> {
                // Production confirmation will be mapped after dry-run tests pass.
                Prefs.status(this, "Đang chờ xác nhận Story đã đăng")
            }
        }
    }

    private fun reportAndClear(jobId: String, state: String, note: String) {
        Thread {
            try {
                ApiClient(this).result(jobId, state, note = note)
                Prefs.clearJob(this)
            } catch (e: Exception) {
                Prefs.status(this, "Không gửi được kết quả: ${e.message}")
            }
        }.start()
    }

    private fun normalize(value: CharSequence?): String =
        value?.toString()?.trim()?.lowercase().orEmpty()

    private fun matches(node: AccessibilityNodeInfo, terms: List<String>): Boolean {
        if (node.className?.toString()?.contains("EditText", ignoreCase = true) == true) return false
        val text = normalize(node.text)
        val desc = normalize(node.contentDescription)
        return terms.any { term ->
            val t = term.lowercase()
            text == t || desc == t || text.contains(t) || desc.contains(t)
        }
    }

    private fun findAny(root: AccessibilityNodeInfo, terms: List<String>): AccessibilityNodeInfo? {
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        var seen = 0
        while (queue.isNotEmpty() && seen < 600) {
            val node = queue.removeFirst()
            seen++
            if (matches(node, terms)) return node
            for (i in 0 until node.childCount) {
                node.getChild(i)?.let { queue.add(it) }
            }
        }
        return null
    }

    private fun hasAny(root: AccessibilityNodeInfo, terms: List<String>): Boolean =
        findAny(root, terms) != null

    private fun clickAny(root: AccessibilityNodeInfo, terms: List<String>): Boolean =
        findAny(root, terms)?.let { clickNode(it) } ?: false

    private fun clickNode(node: AccessibilityNodeInfo): Boolean {
        var current: AccessibilityNodeInfo? = node
        var depth = 0
        while (current != null && depth < 5) {
            if (current.isClickable && current.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true
            current = current.parent
            depth++
        }
        return false
    }

    private fun editableNodes(root: AccessibilityNodeInfo): List<AccessibilityNodeInfo> {
        val out = mutableListOf<AccessibilityNodeInfo>()
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        var seen = 0
        while (queue.isNotEmpty() && seen < 600) {
            val node = queue.removeFirst()
            seen++
            val klass = node.className?.toString().orEmpty()
            if (node.isEditable || klass.contains("EditText", ignoreCase = true)) out.add(node)
            for (i in 0 until node.childCount) node.getChild(i)?.let { queue.add(it) }
        }
        return out
    }

    private fun setNodeText(node: AccessibilityNodeInfo, value: String): Boolean {
        if (value.isBlank()) return false
        val args = Bundle()
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value)
        return node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }

    private fun saveUiDiagnostic(root: AccessibilityNodeInfo) {
        val labels = linkedSetOf<String>()
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        var seen = 0
        while (queue.isNotEmpty() && seen < 500 && labels.size < 80) {
            val node = queue.removeFirst()
            seen++
            val klass = node.className?.toString().orEmpty()
            if (!klass.contains("EditText", ignoreCase = true)) {
                if (node.isClickable || klass.contains("Button", ignoreCase = true)) {
                    node.text?.toString()?.trim()?.takeIf { it.isNotBlank() }?.let { labels.add(it.take(100)) }
                    node.contentDescription?.toString()?.trim()?.takeIf { it.isNotBlank() }?.let { labels.add(it.take(100)) }
                }
            }
            for (i in 0 until node.childCount) node.getChild(i)?.let { queue.add(it) }
        }
        Prefs.store(this).edit().putString("last_ui_dump", labels.joinToString(" | ")).apply()
    }

    override fun onInterrupt() {
        Prefs.status(this, "Accessibility bị tạm ngắt")
    }
}
