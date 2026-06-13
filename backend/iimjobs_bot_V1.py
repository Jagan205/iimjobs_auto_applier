import json
import time
import traceback
import re
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import sync_playwright

from config import (
    IIMJOBS_EMAIL,
    IIMJOBS_PASSWORD,
    RESUME_PATH,
    HEADLESS,
    MAX_JOBS_PER_KEYWORD,
    APPLIED_JOBS_FILE,
    LOG_FILE,
)

runtime_state = {
    "running": False,
    "stop_requested": False,
    "current_keyword": "",
    "current_job": "",
    "logs": [],
    "applied": 0,
    "skipped": 0,
    "failed": 0,
}


def get_runtime_state():
    return runtime_state


def reset_runtime_state():
    runtime_state.update({
        "running": False,
        "stop_requested": False,
        "current_keyword": "",
        "current_job": "",
        "logs": [],
        "applied": 0,
        "skipped": 0,
        "failed": 0,
    })


def log(message: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
    print(line, flush=True)
    runtime_state["logs"].append(line)
    runtime_state["logs"] = runtime_state["logs"][-250:]
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_applied():
    if not APPLIED_JOBS_FILE.exists():
        return []
    try:
        return json.loads(APPLIED_JOBS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def write_applied(items):
    APPLIED_JOBS_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    url = url.split("#")[0]
    # Keep query out for dedupe, because same job may have tracking params.
    url = url.split("?")[0]
    return url.rstrip("/")


def is_iimjobs_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        return "iimjobs.com" in host
    except Exception:
        return False


def is_category_or_nav_link(url: str) -> bool:
    if not url:
        return True

    u = url.lower()

    blocked_patterns = [
        "?ref=nav",
        "&ref=nav",
        "/c/",
        "/k/",
        "/courses",
        "/course",
        "/login",
        "/logout",
        "/register",
        "/recruiter",
        "/applied-jobs",
        "/jobfeed",
        "/jobfeed?",
        "/search",
        "/search?",
        "/myprofile",
        "/profile",
        "/settings",
        "/privacy",
        "/terms",
        "/contact",
        "/about",
    ]

    return any(p in u for p in blocked_patterns)


def looks_like_real_job_url(url: str) -> bool:
    """
    IIMJobs URLs may vary, so we accept only URLs that look like individual job detail pages.
    We explicitly reject category/nav/search pages.
    """
    if not url or not is_iimjobs_url(url) or is_category_or_nav_link(url):
        return False

    parsed = urlparse(url)
    path = parsed.path.lower().rstrip("/")

    # Real IIMJobs job URLs commonly contain numeric job ids or job slug paths.
    # Examples may look like:
    # /j/role-company-location-123456.html
    # /job/.../123456
    # /role-title-company-location-123456.html
    if re.search(r"/j/", path):
        return True

    if re.search(r"/job/", path):
        return True

    if re.search(r"\d{5,}", path):
        return True

    if path.endswith(".html") and len(path.split("/")) >= 2:
        return True

    return False


def keyword_matches_job_text(text: str, keyword: str) -> bool:
    if not keyword:
        return True

    t = (text or "").lower()
    k = keyword.lower().strip()

    if k in t:
        return True

    # Loose matching: all important tokens should appear.
    tokens = [x for x in re.split(r"[^a-z0-9]+", k) if len(x) >= 3]
    if not tokens:
        return True

    return all(tok in t for tok in tokens[:4])


class IIMJobsBot:
    """
    Playwright-based IIMJobs automation.

    Important:
    - First run HEADLESS=false.
    - If captcha/OTP/security check appears, complete manually.
    - This updated version avoids category/navigation links and only attempts real job pages.
    """

    def __init__(self):
        self.applied_items = read_applied()
        self.applied_urls = {normalize_url(x.get("url", "")) for x in self.applied_items}

    def validate_config(self):
        if not IIMJOBS_EMAIL:
            raise ValueError("IIMJOBS_EMAIL missing in .env")
        if not IIMJOBS_PASSWORD:
            raise ValueError("IIMJOBS_PASSWORD missing in .env")
        if not RESUME_PATH:
            raise ValueError("RESUME_PATH missing in .env")
        if not Path(RESUME_PATH).exists():
            raise FileNotFoundError(f"Resume file not found: {RESUME_PATH}")

    def run(self, keywords):
        runtime_state["running"] = True
        log("Bot started.")

        try:
            self.validate_config()

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=HEADLESS,
                    slow_mo=300 if not HEADLESS else 0
                )
                context = browser.new_context(
                    viewport={"width": 1440, "height": 950}
                )
                page = context.new_page()

                self.login(page)

                for keyword in keywords:
                    if runtime_state.get("stop_requested"):
                        log("Stop requested. Exiting.")
                        break

                    runtime_state["current_keyword"] = keyword
                    self.process_keyword(page, keyword)

                browser.close()

        except Exception as e:
            runtime_state["failed"] += 1
            log(f"Fatal error: {e}")
            log(traceback.format_exc())

        finally:
            runtime_state["running"] = False
            log("Bot finished.")

    def login(self, page):
        log("Opening IIMJobs login page...")
        page.goto("https://www.iimjobs.com/login", wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)

        # If redirected away from login, assume session active.
        if "login" not in page.url.lower():
            log("Already logged in or session active.")
            return

        log("Trying to login...")

        self.fill_first(page, [
            'input[type="email"]',
            'input[name="email"]',
            'input[name="username"]',
            'input[id*="email" i]',
            'input[placeholder*="email" i]',
            'input[placeholder*="username" i]',
            'input[autocomplete="username"]',
        ], IIMJOBS_EMAIL)

        self.fill_first(page, [
            'input[type="password"]',
            'input[name="password"]',
            'input[id*="password" i]',
            'input[placeholder*="password" i]',
            'input[autocomplete="current-password"]',
        ], IIMJOBS_PASSWORD)

        clicked = self.click_first(page, [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Login")',
            'button:has-text("Sign In")',
            'text=Login',
            'text=Sign In',
        ])

        if not clicked:
            raise RuntimeError("Could not find login button. Website UI may have changed.")

        log("Login submitted. Waiting...")
        time.sleep(5)

        if "login" in page.url.lower():
            log("Still on login page. If captcha/OTP appears, complete manually in browser.")
            try:
                page.wait_for_url(lambda url: "login" not in url.lower(), timeout=120000)
            except Exception:
                log("Login did not complete automatically. Check credentials/captcha.")
                return

        log("Login completed or session active.")

    def process_keyword(self, page, keyword):
        log(f"Searching keyword: {keyword}")

        search_urls = [
            f"https://www.iimjobs.com/jobfeed?search={quote_plus(keyword)}",
            f"https://www.iimjobs.com/jobfeed?keyword={quote_plus(keyword)}",
            "https://www.iimjobs.com/jobfeed",
        ]

        loaded = False
        for url in search_urls:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                if "iimjobs.com" in page.url:
                    loaded = True
                    break
            except Exception as e:
                log(f"Search URL failed: {url} | {e}")

        if not loaded:
            log(f"Could not open search page for keyword: {keyword}")
            runtime_state["failed"] += 1
            return

        self.try_search_box(page, keyword)

        # Scroll to load more results.
        self.scroll_results(page)

        job_links = self.collect_job_links(page, keyword)
        log(f"Collected {len(job_links)} real job links for keyword: {keyword}")

        if not job_links:
            log("No real job links found. Category/nav links were ignored.")
            return

        count = 0
        for job_url in job_links:
            if runtime_state.get("stop_requested"):
                log("Stop requested. Stopping after current keyword.")
                return

            if count >= MAX_JOBS_PER_KEYWORD:
                log(f"Reached MAX_JOBS_PER_KEYWORD={MAX_JOBS_PER_KEYWORD}")
                break

            norm = normalize_url(job_url)
            if norm in self.applied_urls:
                log(f"Skipping locally tracked job: {job_url}")
                runtime_state["skipped"] += 1
                continue

            self.apply_job(page, job_url, keyword)
            count += 1

    def try_search_box(self, page, keyword):
        selectors = [
            'input[type="search"]',
            'input[placeholder*="search" i]',
            'input[placeholder*="keyword" i]',
            'input[name*="search" i]',
            'input[name*="keyword" i]',
        ]

        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.fill(keyword)
                    loc.press("Enter")
                    time.sleep(4)
                    log("Searched using visible search box.")
                    return True
            except Exception:
                pass

        log("Visible search box not found. Using loaded jobfeed links.")
        return False

    def scroll_results(self, page):
        try:
            for _ in range(5):
                page.mouse.wheel(0, 2200)
                time.sleep(1)
        except Exception:
            pass

    def collect_job_links(self, page, keyword):
        """
        Updated link collector:
        - Rejects category/navigation/search/profile links.
        - Accepts only job-detail-looking URLs.
        - Avoids false applied tracking.
        """
        links = []
        seen = set()

        anchors = page.locator("a")
        try:
            total = min(anchors.count(), 800)
        except Exception:
            total = 0

        log(f"Scanning {total} links on search page...")

        for i in range(total):
            try:
                a = anchors.nth(i)
                href = a.get_attribute("href")
                text = (a.inner_text(timeout=1000) or "").strip()

                if not href:
                    continue

                if href.startswith("/"):
                    href = "https://www.iimjobs.com" + href

                href = href.strip()
                norm = normalize_url(href)

                if norm in seen:
                    continue

                if not looks_like_real_job_url(href):
                    continue

                # Avoid very generic cards/ads.
                combined = f"{text} {href}"
                if text and not keyword_matches_job_text(combined, keyword):
                    # Do not skip too aggressively because sometimes title text is nested elsewhere.
                    pass

                seen.add(norm)
                links.append(href)
                log(f"Job link accepted: {href}")

            except Exception:
                continue

        # Fallback: parse hrefs from page HTML.
        if not links:
            try:
                html = page.content()
                for href in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I):
                    if href.startswith("/"):
                        href = "https://www.iimjobs.com" + href
                    norm = normalize_url(href)
                    if norm in seen:
                        continue
                    if looks_like_real_job_url(href):
                        seen.add(norm)
                        links.append(href)
                        log(f"Fallback job link accepted: {href}")
            except Exception:
                pass

        return links

    def apply_job(self, page, job_url, keyword):
        runtime_state["current_job"] = job_url
        log(f"Opening job: {job_url}")

        try:
            page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

            # Final safety check: do not apply on category pages.
            if is_category_or_nav_link(page.url) or not looks_like_real_job_url(page.url):
                log(f"Safety skip. Not a real job detail page: {page.url}")
                runtime_state["skipped"] += 1
                return

            title = self.get_page_title(page)
            log(f"Job title: {title}")

            if self.is_already_applied(page):
                log("Portal says already applied. Recording as already_applied.")
                self.record_job(job_url, title, keyword, status="already_applied")
                runtime_state["skipped"] += 1
                return

            applied = self.click_apply_flow(page)

            if applied:
                # Verify after click.
                time.sleep(2)
                if self.is_already_applied(page) or self.is_success_message(page):
                    self.record_job(job_url, title, keyword, status="applied")
                    runtime_state["applied"] += 1
                    log("Applied successfully and confirmation detected.")
                else:
                    # Store as attempted, not applied, to avoid false confidence.
                    self.record_job(job_url, title, keyword, status="attempted_needs_verification")
                    runtime_state["failed"] += 1
                    log("Apply attempted, but confirmation not detected. Please verify manually.")
            else:
                runtime_state["failed"] += 1
                log("Could not find/click Apply button.")

        except Exception as e:
            runtime_state["failed"] += 1
            log(f"Failed job: {job_url} | Error: {e}")

    def click_apply_flow(self, page):
        clicked = self.click_first(page, [
            'button:has-text("Apply")',
            'a:has-text("Apply")',
            'div:has-text("Apply")',
            'span:has-text("Apply")',
            'button:has-text("Apply Now")',
            'a:has-text("Apply Now")',
            'text=Apply Now',
            'text=Apply',
        ])

        if not clicked:
            return False

        log("Apply button clicked.")
        time.sleep(2)

        # Upload resume if file input appears.
        try:
            file_inputs = page.locator('input[type="file"]')
            if file_inputs.count() > 0:
                file_inputs.first.set_input_files(RESUME_PATH)
                log("Resume uploaded.")
                time.sleep(2)
        except Exception as e:
            log(f"Resume upload not found or failed: {e}")

        # Confirm/Submit if modal appears.
        confirm_clicked = self.click_first(page, [
            'button:has-text("Submit")',
            'button:has-text("Confirm")',
            'button:has-text("Apply")',
            'button:has-text("Send")',
            'button:has-text("Continue")',
            'text=Submit',
            'text=Confirm',
            'text=Continue',
        ])

        if confirm_clicked:
            log("Confirmation/submit button clicked.")
            time.sleep(3)

        return True

    def is_already_applied(self, page):
        text = self.page_text(page).lower()
        phrases = [
            "already applied",
            "applied already",
            "you have applied",
            "application submitted",
            "applied/sent",
            "applied on",
        ]
        return any(p in text for p in phrases)

    def is_success_message(self, page):
        text = self.page_text(page).lower()
        phrases = [
            "successfully applied",
            "application submitted",
            "your application has been submitted",
            "applied successfully",
            "applied/sent",
        ]
        return any(p in text for p in phrases)

    def page_text(self, page):
        try:
            return page.locator("body").inner_text(timeout=5000)
        except Exception:
            return ""

    def get_page_title(self, page):
        for sel in ["h1", "h2", '[class*="title" i]', '[class*="job" i] h1', '[class*="job" i] h2']:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    txt = loc.inner_text(timeout=3000).strip()
                    if txt and len(txt) > 3:
                        return txt[:180]
            except Exception:
                pass

        try:
            return page.title()
        except Exception:
            return "Unknown Job"

    def record_job(self, url, title, keyword, status):
        item = {
            "url": url,
            "title": title,
            "keyword": keyword,
            "status": status,
            "applied_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.applied_items.append(item)
        self.applied_urls.add(normalize_url(url))
        write_applied(self.applied_items)

    def fill_first(self, page, selectors, value):
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.fill(value)
                    return True
            except Exception:
                pass
        raise RuntimeError(f"Could not find input field among selectors: {selectors}")

    def click_first(self, page, selectors):
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=7000)
                    return True
            except Exception:
                pass
        return False
