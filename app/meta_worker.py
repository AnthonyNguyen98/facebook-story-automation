from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright

from .settings import settings


class MetaUIError(RuntimeError):
    pass


class MetaWorker:
    def __init__(self, screenshot_dir: Path):
        self.screenshot_dir = screenshot_dir
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def _seed_state(self) -> None:
        path = Path(settings.meta_storage_state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() and settings.meta_storage_state_b64:
            path.write_bytes(base64.b64decode(settings.meta_storage_state_b64))

    def _session_metadata(self, state_path: Path) -> str:
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return f"state_read_error={type(exc).__name__}"

        cookies = data.get("cookies") or []
        auth_names = {"c_user", "xs", "fr", "datr", "sb"}
        auth = [c for c in cookies if c.get("name") in auth_names]
        present = sorted({c.get("name", "") for c in auth if c.get("name")})
        missing_critical = [name for name in ("c_user", "xs") if name not in present]
        now = time.time()
        meta = []
        for c in auth:
            exp = c.get("expires", -1)
            if not isinstance(exp, (int, float)) or exp < 0:
                expiry = "session"
            else:
                expiry = f"{int(exp - now)}s"
            meta.append(f"{c.get('name')}@{c.get('domain')}:{expiry}")
        origins = data.get("origins") or []
        origin_hosts = []
        for item in origins[:10]:
            origin = str(item.get("origin", ""))
            if origin:
                origin_hosts.append(origin[:100])
        return (
            f"cookie_count={len(cookies)}; auth_present={present}; "
            f"missing_critical={missing_critical}; auth_meta={meta}; "
            f"origin_count={len(origins)}; origins={origin_hosts}"
        )

    async def _one(self, page: Page, patterns: list[str], role: str = "button"):
        matches = []
        for p in patterns:
            loc = page.get_by_role(role, name=re.compile(p, re.I))
            if await loc.count() == 1:
                return loc
            if await loc.count() > 1:
                matches.append((p, await loc.count()))
        raise MetaUIError(f"Could not uniquely locate {role}: {patterns}; matches={matches}")

    async def _diagnostic(self, page: Page, job_id: str, state_meta: str, user_agent: str) -> str:
        shot = self.screenshot_dir / f"{job_id}_meta_failure.png"
        try:
            await page.screenshot(path=str(shot), full_page=True)
        except Exception:
            pass
        try:
            title = await page.title()
        except Exception:
            title = ""
        try:
            buttons = await page.get_by_role("button").all_inner_texts()
        except Exception:
            buttons = []
        clean_buttons = []
        for value in buttons[:60]:
            value = " ".join((value or "").split())
            if value and value not in clean_buttons:
                clean_buttons.append(value[:100])
        return (
            f"url={page.url}; title={title[:150]!r}; buttons={clean_buttons[:40]!r}; "
            f"user_agent={user_agent[:180]!r}; session_meta=({state_meta}); screenshot={shot}"
        )

    async def publish(self, media: Path, link_url: str, link_text: str, job_id: str) -> Path:
        self._seed_state()
        state_path = Path(settings.meta_storage_state_path)
        if not state_path.exists():
            raise MetaUIError("META_SESSION_NOT_BOOTSTRAPPED")
        state_meta = self._session_metadata(state_path)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=settings.headless)
            context = await browser.new_context(storage_state=str(state_path), viewport={"width": 1440, "height": 1000})
            page = await context.new_page()
            try:
                try:
                    user_agent = await page.evaluate("navigator.userAgent")
                except Exception:
                    user_agent = ""
                await page.goto(settings.meta_business_url, wait_until="domcontentloaded", timeout=90000)
                await page.wait_for_timeout(2500)
                if "login" in page.url.lower():
                    raise MetaUIError("META_SESSION_EXPIRED")
                create_btn = await self._one(page, [r"^Create story$", r"^Tạo tin$", r"^Tạo story$"])
                await create_btn.click()
                await page.wait_for_timeout(1200)
                upload = page.locator('input[type="file"]')
                if await upload.count() < 1:
                    raise MetaUIError("STORY_FILE_INPUT_NOT_FOUND")
                await upload.first.set_input_files(str(media))
                await page.wait_for_timeout(2500)
                link_btn = await self._one(page, [r"^Link$", r"^Liên kết$"])
                await link_btn.click()
                await page.wait_for_timeout(700)
                url_fields = page.get_by_role("textbox", name=re.compile(r"URL|Link|Liên kết|Website", re.I))
                if await url_fields.count() < 1:
                    url_fields = page.locator('input[type="url"]')
                if await url_fields.count() < 1:
                    raise MetaUIError("LINK_URL_FIELD_NOT_FOUND")
                await url_fields.first.fill(link_url)
                text_fields = page.get_by_role("textbox", name=re.compile(r"link text|display text|text.*link|văn bản.*liên kết|nội dung.*liên kết", re.I))
                if await text_fields.count() >= 1:
                    await text_fields.first.fill(link_text)
                elif settings.strict_link_text:
                    raise MetaUIError("LINK_TEXT_FIELD_NOT_FOUND")
                confirm = page.get_by_role("button", name=re.compile(r"^Done$|^Xong$|^Add$|^Thêm$", re.I))
                if await confirm.count() == 1:
                    await confirm.click()
                    await page.wait_for_timeout(500)
                shot = self.screenshot_dir / f"{job_id}_before_publish.png"
                await page.screenshot(path=str(shot), full_page=True)
                if settings.dry_run:
                    await context.storage_state(path=str(state_path))
                    return shot
                publish_btn = await self._one(page, [r"Share.*story", r"Chia sẻ.*tin", r"^Publish$", r"^Đăng$"])
                await publish_btn.click()
                await page.wait_for_timeout(4000)
                await context.storage_state(path=str(state_path))
                return shot
            except Exception as exc:
                try:
                    user_agent
                except NameError:
                    user_agent = ""
                diag = await self._diagnostic(page, job_id, state_meta, user_agent)
                raise MetaUIError(f"{exc}; META_DIAG {diag}") from exc
            finally:
                await context.close()
                await browser.close()
