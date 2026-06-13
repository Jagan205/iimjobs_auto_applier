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


GENERIC_WORDS = {
    "job", "jobs", "role", "roles", "opening", "openings", "hiring",
    "urgent", "manager", "senior", "sr", "lead", "associate", "analyst",
    "executive", "specialist", "consultant", "india", "mumbai", "delhi",
    "bangalore", "bengaluru", "chennai", "hyderabad", "pune", "remote",
    "onsite", "hybrid"
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
    runtime_state["logs"] = runtime_state["logs"][-300:]
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


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip().split("#")[0].split("?")[0]
    return url.rstrip("/")


def tokenize(text: str):
    tokens = re.split(r"[^a-zA-Z0-9+#.]+", (text or "").lower())
    return [t.strip() for t in tokens if len(t.strip()) >= 2]


def important_tokens(keyword: str):
    toks = tokenize(keyword)
    return [t for t in toks if t not in GENERIC_WORDS and len(t) >= 3]


def phrase_in_text(phrase: str, text: str) -> bool:
    p = clean_text(phrase).lower()
    t = clean_text(text).lower()
    return bool(p and p in t)


def is_iimjobs_url(url: str) -> bool:
    try:
        return "iimjobs.com" in urlparse(url).netloc.lower()
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
    if not url or not is_iimjobs_url(url) or is_category_or_nav_link(url):
        return False

    path = urlparse(url).path.lower().rstrip("/")

    if re.search(r"/j/", path):
        return True

    if re.search(r"/job/", path):
        return True

    if re.search(r"\d{5,}", path):
        return True

    if path.endswith(".html") and len(path.split("/")) >= 2:
        return True

    return False


def keyword_relevance_score(keyword: str, title: str, body: str):
    """
    Dynamic strict matching.

    Works for any search role:
      - chief of staff
      - pharmaceutical
      - life science
      - data engineer
      - product manager
      - finance analyst
      - marketing head

    Rules:
      1. Exact phrase in title => apply.
      2. Exact phrase in description => apply.
      3. All important keyword tokens in title => apply.
      4. All important keyword tokens in title + description => apply.
      5. Weak partial token match => skip.

    This avoids applying to random jobs just because search page returned them.
    """

    keyword = clean_text(keyword).lower()
    title_l = clean_text(title).lower()
    body_l = clean_text(body).lower()
    full_text = f"{title_l} {body_l}"

    if not keyword:
        return 0, "empty keyword"

    # Exact phrase match is strongest.
    if phrase_in_text(keyword, title_l):
        return 100, f'exact search role found in title: "{keyword}"'

    if phrase_in_text(keyword, body_l):
        return 85, f'exact search role found in description: "{keyword}"'

    tokens = important_tokens(keyword)

    if not tokens:
        tokens = tokenize(keyword)

    if not tokens:
        return 0, "no usable keyword tokens"

    title_tokens = set(tokenize(title_l))
    full_tokens = set(tokenize(full_text))

    matched_title = [t for t in tokens if t in title_tokens]
    matched_full = [t for t in tokens if t in full_tokens]

    # All meaningful tokens in title is strong.
    if len(matched_title) == len(tokens):
        return 80, f'all role tokens found in title: {tokens}'

    # All meaningful tokens anywhere in job page is acceptable.
    if len(matched_full) == len(tokens):
        return 70, f'all role tokens found in job page: {tokens}'

    # Single meaningful keyword like pharmaceutical, fintech, healthcare, databricks.
    if len(tokens) == 1 and tokens[0] in full_tokens:
        return 70, f'single role token matched in job page: {tokens[0]}'

    # Multi-word role should not pass with only one token.
    return 0, f'keyword mismatch. Need tokens {tokens}, found {matched_full}'


def should_apply_for_keyword(keyword: str, title: str, body: str):
    score, reason = keyword_relevance_score(keyword, title, body)
    if score >= 70:
        return True, score, reason
    return False, score, reason


class IIMJobsBot:
    """
    IIMJobs automation.

    Updated behavior:
    - Uses whatever roles user entered in UI.
    - Opens candidate job page.
    - Reads actual title and body.
    - Applies only when the current search role strictly matches title/body.
    - Skips unrelated results even if IIMJobs search returned them.
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
        log(f"Search roles from UI: {keywords}")

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
                    keyword = clean_text(keyword)
                    if not keyword:
                        continue

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
        log(f"Searching role: {keyword}")

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
            log(f"Could not open search page for role: {keyword}")
            runtime_state["failed"] += 1
            return

        self.try_search_box(page, keyword)
        self.scroll_results(page)

        job_links = self.collect_job_links(page)
        log(f"Collected {len(job_links)} candidate job links for role: {keyword}")

        if not job_links:
            log("No real job links found. Category/nav links were ignored.")
            return

        processed = 0

        for job_url in job_links:
            if runtime_state.get("stop_requested"):
                log("Stop requested. Stopping after current role.")
                return

            if processed >= MAX_JOBS_PER_KEYWORD:
                log(f"Reached MAX_JOBS_PER_KEYWORD={MAX_JOBS_PER_KEYWORD}")
                break

            norm = normalize_url(job_url)
            if norm in self.applied_urls:
                log(f"Skipping locally tracked job: {job_url}")
                runtime_state["skipped"] += 1
                continue

            self.apply_job(page, job_url, keyword)
            processed += 1

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

    def collect_job_links(self, page):
        links = []
        seen = set()

        anchors = page.locator("a")
        try:
            total = min(anchors.count(), 900)
        except Exception:
            total = 0

        log(f"Scanning {total} links on search page...")

        for i in range(total):
            try:
                a = anchors.nth(i)
                href = a.get_attribute("href")

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

                seen.add(norm)
                links.append(href)
                log(f"Accepted real job link: {href}")

            except Exception:
                continue

        # Fallback parse HTML for job hrefs.
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
                        log(f"Fallback accepted real job link: {href}")
            except Exception:
                pass

        return links

    def apply_job(self, page, job_url, keyword):
        runtime_state["current_job"] = job_url
        log(f"Opening candidate job: {job_url}")

        try:
            page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

            if is_category_or_nav_link(page.url) or not looks_like_real_job_url(page.url):
                log(f"Safety skip. Not a real job detail page: {page.url}")
                runtime_state["skipped"] += 1
                return

            title = self.get_page_title(page)
            body = self.page_text(page)

            log(f"Job title detected: {title}")

            should_apply, score, reason = should_apply_for_keyword(keyword, title, body)

            if not should_apply:
                log(f"SKIPPED - role mismatch for search role '{keyword}'. Score={score}. Reason={reason}")
                self.record_job(job_url, title, keyword, status="skipped_role_mismatch", reason=reason)
                runtime_state["skipped"] += 1
                return

            log(f"RELEVANT - applying for role '{keyword}'. Score={score}. Reason={reason}")

            if self.is_already_applied(page):
                log("Portal says already applied. Recording as already_applied.")
                self.record_job(job_url, title, keyword, status="already_applied", reason="portal already applied")
                runtime_state["skipped"] += 1
                return

            applied = self.click_apply_flow(page)

            if applied:
                time.sleep(2)

                if self.is_already_applied(page) or self.is_success_message(page):
                    self.record_job(job_url, title, keyword, status="applied", reason=reason)
                    runtime_state["applied"] += 1
                    log("Applied successfully and confirmation detected.")
                else:
                    self.record_job(job_url, title, keyword, status="attempted_needs_verification", reason=reason)
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

        try:
            file_inputs = page.locator('input[type="file"]')
            if file_inputs.count() > 0:
                file_inputs.first.set_input_files(RESUME_PATH)
                log("Resume uploaded.")
                time.sleep(2)
        except Exception as e:
            log(f"Resume upload not found or failed: {e}")

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
        for sel in [
            "h1",
            "h2",
            '[class*="title" i]',
            '[class*="job" i] h1',
            '[class*="job" i] h2'
        ]:
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

    def record_job(self, url, title, keyword, status, reason=""):
        item = {
            "url": url,
            "title": title,
            "keyword": keyword,
            "status": status,
            "reason": reason,
            "applied_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        self.applied_items.append(item)

        # Track skipped mismatch also, so the same unrelated job is not reprocessed repeatedly.
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
