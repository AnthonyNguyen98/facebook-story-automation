package vn.megas.storycompanion

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UiMatcherTest {
    @Test
    fun exactPublishDoesNotMatchLogin() {
        assertTrue(UiMatcher.exact("Đăng", listOf("Đăng")))
        assertFalse(UiMatcher.exact("Đăng nhập", listOf("Đăng")))
        assertFalse(UiMatcher.exact("Đăng bài", listOf("Đăng")))
    }

    @Test
    fun exactLinkDoesNotMatchLongerLabels() {
        assertTrue(UiMatcher.exact("Link", listOf("Link")))
        assertFalse(UiMatcher.exact("Link settings", listOf("Link")))
        assertFalse(UiMatcher.exact("Copy link", listOf("Link")))
    }

    @Test
    fun normalizationHandlesCaseAndWhitespaceOnly() {
        assertTrue(UiMatcher.exact("  CREATE   STORY  ", listOf("Create story")))
        assertTrue(UiMatcher.exact("TẠO TIN", listOf("tạo tin")))
    }

    @Test
    fun substringIsNeverEnough() {
        assertFalse(UiMatcher.exact("Tạo tin mới", listOf("Tạo tin")))
        assertFalse(UiMatcher.exact("Ảnh/Video khác", listOf("Ảnh/Video")))
    }

    @Test
    fun emptyValuesNeverMatch() {
        assertFalse(UiMatcher.exact(null, listOf("Link")))
        assertFalse(UiMatcher.exact("", listOf("")))
        assertFalse(UiMatcher.exactEither(null, null, listOf("Create story")))
    }

    @Test
    fun descriptionCanMatchWhenTextDoesNot() {
        assertTrue(UiMatcher.exactEither("", "Create story", listOf("Create story")))
        assertFalse(UiMatcher.exactEither("Other", "Create story now", listOf("Create story")))
    }
}
