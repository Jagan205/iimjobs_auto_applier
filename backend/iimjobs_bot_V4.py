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


def normalize_for_match(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9+#.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip().split("#")[0].split("?")[0]
    return url.rstrip("/")


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
        "?ref=nav", "&ref=nav", "/c/", "/k/", "/courses", "/course",
        "/login", "/logout", "/register", "/recruiter", "/applied-jobs",
        "/jobfeed", "/jobfeed?", "/search", "/search?", "/myprofile",
        "/profile", "/settings", "/privacy", "/terms", "/contact", "/about",
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


def build_keyword_variants(keyword: str):
    k = normalize_for_match(keyword)
    variants = set()

    if not k:
        return []

    variants.add(k)

    if k.endswith("s"):
        variants.add(k[:-1])
    else:
        variants.add(k + "s")

    synonym_map = {
        "life science": ["life science", "life sciences"],
        "life sciences": ["life science", "life sciences"],
        "pharmaceutical": ["pharmaceutical", "pharmaceuticals", "pharma"],
        "pharmaceuticals": ["pharmaceutical", "pharmaceuticals", "pharma"],
        "pharma": ["pharmaceutical", "pharmaceuticals", "pharma"],
        "data engineer": ["data engineer", "data engineering"],
        "data engineering": ["data engineer", "data engineering"],
        "chief of staff": ["chief of staff"],
    }

    if k in synonym_map:
        variants.update(synonym_map[k])

    return sorted(variants, key=len, reverse=True)


def phrase_match(variant: str, text: str):
    if not variant:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(variant) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def match_any_phrase(values, text, label):
    text_norm = normalize_for_match(text)

    for value in values or []:
        variants = build_keyword_variants(value)
        for v in variants:
            if phrase_match(v, text_norm):
                return True, f'{label} matched: "{v}"'

    return False, f"no {label} match"


def should_apply(role, jd_keywords, locations, title, main_job_text, location_text):
    role_ok, role_reason = match_any_phrase([role], f"{title} {main_job_text}", "role")
    keyword_ok, keyword_reason = match_any_phrase(jd_keywords, f"{title} {main_job_text}", "JD keyword")

    if locations:
        location_ok, location_reason = match_any_phrase(locations, location_text, "location")
    else:
        location_ok, location_reason = True, "location filter empty, allowing all locations"

    if role_ok and keyword_ok and location_ok:
        return True, f"{role_reason}; {keyword_reason}; {location_reason}"

    return False, f"{role_reason}; {keyword_reason}; {location_reason}"


class IIMJobsBot:
    """
    Applies only when:
      Job Role match in MAIN JOB CONTENT
      AND JD Keyword match in MAIN JOB CONTENT
      AND Location match in detected location text

    This version avoids matching against sidebars/recommended jobs/filter text.
    """

    def __init__(self):
        self.applied_items = read_applied()
        self.applied_urls = {normalize_url(x.get("url", "")) for x in self.applied_items}
        self.jd_keywords = []
        self.locations = []

    def validate_config(self):
        if not IIMJOBS_EMAIL:
            raise ValueError("IIMJOBS_EMAIL missing in .env")
        if not IIMJOBS_PASSWORD:
            raise ValueError("IIMJOBS_PASSWORD missing in .env")
        if not RESUME_PATH:
            raise ValueError("RESUME_PATH missing in .env")
        if not Path(RESUME_PATH).exists():
            raise FileNotFoundError(f"Resume file not found: {RESUME_PATH}")

    def run(self, roles, jd_keywords=None, locations=None):
        self.jd_keywords = [clean_text(x) for x in (jd_keywords or []) if clean_text(x)]
        self.locations = [clean_text(x) for x in (locations or []) if clean_text(x)]

        runtime_state["running"] = True
        log("Bot started.")
        log(f"Roles: {roles}")
        log(f"JD Keywords: {self.jd_keywords}")
        log(f"Locations: {self.locations if self.locations else 'ALL'}")
        log("Apply rule: ROLE match AND JD KEYWORD match AND LOCATION match")
        log("Matching scope: MAIN JOB CONTENT ONLY, not full page body.")

        try:
            self.validate_config()

            if not self.jd_keywords:
                raise ValueError("At least one JD keyword is required because matching uses Role AND Keywords.")

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=HEADLESS,
                    slow_mo=300 if not HEADLESS else 0
                )
                context = browser.new_context(viewport={"width": 1440, "height": 950})
                page = context.new_page()

                self.login(page)

                for role in roles:
                    role = clean_text(role)
                    if not role:
                        continue

                    if runtime_state.get("stop_requested"):
                        log("Stop requested. Exiting.")
                        break

                    runtime_state["current_keyword"] = role
                    self.process_role(page, role)

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

        self.fill_first(page, [
            'input[type="email"]', 'input[name="email"]', 'input[name="username"]',
            'input[id*="email" i]', 'input[placeholder*="email" i]',
            'input[placeholder*="username" i]', 'input[autocomplete="username"]',
        ], IIMJOBS_EMAIL)

        self.fill_first(page, [
            'input[type="password"]', 'input[name="password"]',
            'input[id*="password" i]', 'input[placeholder*="password" i]',
            'input[autocomplete="current-password"]',
        ], IIMJOBS_PASSWORD)

        clicked = self.click_first(page, [
            'button[type="submit"]', 'input[type="submit"]',
            'button:has-text("Login")', 'button:has-text("Sign In")',
            'text=Login', 'text=Sign In',
        ])

        if not clicked:
            raise RuntimeError("Could not find login button.")

        log("Login submitted. Waiting...")
        time.sleep(5)

        if "login" in page.url.lower():
            log("Still on login page. If captcha/OTP appears, complete manually.")
            try:
                page.wait_for_url(lambda url: "login" not in url.lower(), timeout=120000)
            except Exception:
                log("Login did not complete automatically.")
                return

        log("Login completed or session active.")

    def process_role(self, page, role):
        log(f"Searching role: {role}")

        search_urls = [
            f"https://www.iimjobs.com/jobfeed?search={quote_plus(role)}",
            f"https://www.iimjobs.com/jobfeed?keyword={quote_plus(role)}",
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
            log(f"Could not open search page for role: {role}")
            runtime_state["failed"] += 1
            return

        self.try_search_box(page, role)
        self.scroll_results(page)

        job_links = self.collect_job_links(page)
        log(f"Collected {len(job_links)} candidate job links for role: {role}")

        processed = 0

        for job_url in job_links:
            if runtime_state.get("stop_requested"):
                return

            if processed >= MAX_JOBS_PER_KEYWORD:
                log(f"Reached MAX_JOBS_PER_KEYWORD={MAX_JOBS_PER_KEYWORD}")
                break

            norm = normalize_url(job_url)
            if norm in self.applied_urls:
                log(f"Skipping locally tracked job: {job_url}")
                runtime_state["skipped"] += 1
                continue

            self.apply_job(page, job_url, role)
            processed += 1

    def try_search_box(self, page, role):
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
                    loc.fill(role)
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
                href = anchors.nth(i).get_attribute("href")
                if not href:
                    continue

                if href.startswith("/"):
                    href = "https://www.iimjobs.com" + href

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

        return links

    def extract_main_job_text(self, page, title):
        """
        Extract only main job detail content.

        Avoid full body because IIMJobs page can include sidebars/recommended jobs
        containing unrelated words like pharma/hyderabad.
        """
        candidates = []

        selectors = [
            '[class*="job-description" i]',
            '[class*="jobDescription" i]',
            '[class*="description" i]',
            '[class*="jd" i]',
            '[class*="job-detail" i]',
            '[class*="jobDetail" i]',
            '[class*="details" i]',
            'main',
            'article',
            'section',
        ]

        for sel in selectors:
            try:
                locs = page.locator(sel)
                count = min(locs.count(), 20)
                for i in range(count):
                    txt = clean_text(locs.nth(i).inner_text(timeout=2000))
                    if len(txt) > 300:
                        candidates.append(txt)
            except Exception:
                pass

        if not candidates:
            body = clean_text(self.page_text(page))
            candidates.append(body)

        # Pick text chunk that contains title or role markers and is not huge page shell.
        title_norm = normalize_for_match(title)
        best = ""
        best_score = -1

        for txt in candidates:
            n = normalize_for_match(txt)
            score = 0

            if title_norm and title_norm[:40] in n:
                score += 50

            for marker in [
                "job description",
                "job responsibilities",
                "what will this role require",
                "what you need to have",
                "about the role",
                "role:",
                "responsibilities",
                "requirements",
            ]:
                if marker in n:
                    score += 20

            # Prefer not too small, not full-page huge.
            if 500 <= len(txt) <= 12000:
                score += 20

            if len(txt) > len(best):
                score += 1

            if score > best_score:
                best_score = score
                best = txt

        # Remove common unrelated page sections if they appear after JD.
        cut_markers = [
            "similar jobs",
            "recommended jobs",
            "people also viewed",
            "other jobs",
            "apply to similar jobs",
            "jobs you may like",
        ]

        lower = best.lower()
        cut_positions = [lower.find(m) for m in cut_markers if lower.find(m) != -1]
        if cut_positions:
            best = best[:min(cut_positions)]

        return clean_text(best)

    def extract_location_text(self, page, title, main_job_text):
        """
        Prefer visible job header/details text for location.
        Fallback to title + main JD only.
        """
        snippets = [title, main_job_text[:1500]]

        selectors = [
            '[class*="location" i]',
            '[class*="job-location" i]',
            '[class*="jobLocation" i]',
            '[class*="posted" i]',
            '[class*="detail" i]',
            'h1',
            'h2',
        ]

        for sel in selectors:
            try:
                locs = page.locator(sel)
                count = min(locs.count(), 20)
                for i in range(count):
                    txt = clean_text(locs.nth(i).inner_text(timeout=1000))
                    if txt and len(txt) < 800:
                        snippets.append(txt)
            except Exception:
                pass

        return clean_text(" ".join(snippets))

    def apply_job(self, page, job_url, role):
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
            main_job_text = self.extract_main_job_text(page, title)
            location_text = self.extract_location_text(page, title, main_job_text)

            log(f"Job title detected: {title}")
            log(f"Main job text length: {len(main_job_text)}")
            log(f"Location text preview: {location_text[:250]}")

            ok, reason = should_apply(role, self.jd_keywords, self.locations, title, main_job_text, location_text)

            if not ok:
                log(f"SKIPPED - AND condition failed. Role='{role}'. Reason={reason}")
                self.record_job(job_url, title, role, status="skipped_filter_mismatch", reason=reason)
                runtime_state["skipped"] += 1
                return

            log(f"RELEVANT - applying. Role='{role}'. Reason={reason}")

            if self.is_already_applied(page):
                log("Portal says already applied.")
                self.record_job(job_url, title, role, status="already_applied", reason="portal already applied")
                runtime_state["skipped"] += 1
                return

            applied = self.click_apply_flow(page)

            if applied:
                time.sleep(2)

                if self.is_already_applied(page) or self.is_success_message(page):
                    self.record_job(job_url, title, role, status="applied", reason=reason)
                    runtime_state["applied"] += 1
                    log("Applied successfully and confirmation detected.")
                else:
                    self.record_job(job_url, title, role, status="attempted_needs_verification", reason=reason)
                    runtime_state["failed"] += 1
                    log("Apply attempted, but confirmation not detected.")
            else:
                runtime_state["failed"] += 1
                log("Could not find/click Apply button.")

        except Exception as e:
            runtime_state["failed"] += 1
            log(f"Failed job: {job_url} | Error: {e}")

    def click_apply_flow(self, page):
        clicked = self.click_first(page, [
            'button:has-text("Apply")', 'a:has-text("Apply")',
            'div:has-text("Apply")', 'span:has-text("Apply")',
            'button:has-text("Apply Now")', 'a:has-text("Apply Now")',
            'text=Apply Now', 'text=Apply',
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
            'button:has-text("Submit")', 'button:has-text("Confirm")',
            'button:has-text("Apply")', 'button:has-text("Send")',
            'button:has-text("Continue")',
            'text=Submit', 'text=Confirm', 'text=Continue',
        ])

        if confirm_clicked:
            log("Confirmation/submit button clicked.")
            time.sleep(3)

        return True

    def is_already_applied(self, page):
        text = self.page_text(page).lower()
        phrases = [
            "already applied", "applied already", "you have applied",
            "application submitted", "applied/sent", "applied on",
        ]
        return any(p in text for p in phrases)

    def is_success_message(self, page):
        text = self.page_text(page).lower()
        phrases = [
            "successfully applied", "application submitted",
            "your application has been submitted", "applied successfully",
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

    def record_job(self, url, title, role, status, reason=""):
        item = {
            "url": url,
            "title": title,
            "role": role,
            "status": status,
            "reason": reason,
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
