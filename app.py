import streamlit as st
import os
import json
import sqlite3
import requests
import re
from datetime import datetime
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from openai import OpenAI
from supabase import create_client, Client
from fpdf import FPDF
import io
import base64

# ─── SQLite 폴백 DB (Supabase 미설정 시 사용) ───
_SQLITE_DB = "accesscheck_users.db"

def _sqlite_init():
    conn = sqlite3.connect(_SQLITE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT,
            url TEXT,
            score INTEGER,
            total_issues INTEGER,
            result_json TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_email TEXT PRIMARY KEY,
            plan TEXT DEFAULT 'free',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

_sqlite_init()

def _sqlite_save_scan(user_email, url, result):
    conn = sqlite3.connect(_SQLITE_DB)
    conn.execute("""
        INSERT INTO scan_history (user_email, url, score, total_issues, result_json)
        VALUES (?, ?, ?, ?, ?)
    """, (user_email, url, result.get("score", 0), result.get("total_issues", 0), json.dumps(result)))
    conn.commit()
    conn.close()

def _sqlite_load_scans(user_email):
    conn = sqlite3.connect(_SQLITE_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM scan_history WHERE user_email=? ORDER BY created_at DESC LIMIT 10
    """, (user_email,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def _sqlite_is_pro(user_email):
    conn = sqlite3.connect(_SQLITE_DB)
    row = conn.execute("SELECT plan FROM subscriptions WHERE user_email=?", (user_email,)).fetchone()
    conn.close()
    return row and row[0] == "pro"

def _sqlite_set_pro(user_email):
    conn = sqlite3.connect(_SQLITE_DB)
    conn.execute("""
        INSERT INTO subscriptions (user_email, plan) VALUES (?, 'pro')
        ON CONFLICT(user_email) DO UPDATE SET plan='pro'
    """, (user_email,))
    conn.commit()
    conn.close()

APP_VERSION = "2026-04-18-v1"

# ─── Page Config ───
st.set_page_config(
    page_title="AccessCheck AI - WCAG 2.2 Accessibility Scanner",
    page_icon="✅",
    layout="wide"
)

st.markdown("""
    <head>
        <meta name="description" content="AI-powered WCAG 2.2 scanner that generates copy-paste ready code fixes automatically. Free plan includes 3 scans/month. No credit card required.">
        <meta property="og:title" content="AccessCheck AI - WCAG 2.2 Accessibility Scanner">
        <meta property="og:description" content="AI-powered WCAG 2.2 scanner with auto-generated code fixes. Scan any website for WCAG 2.2 violations instantly.">
        <meta property="og:url" content="https://access.trytimeback.com">
        <meta property="og:type" content="website">
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:title" content="AccessCheck AI - WCAG 2.2 Accessibility Scanner">
        <meta name="twitter:description" content="AI-powered WCAG 2.2 scanner with copy-paste ready code fixes.">
    </head>
""", unsafe_allow_html=True)

# ─── Theme CSS ───
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  .main { background: #f8fafc; }

  .hero-banner {
    background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
    border-radius: 16px;
    padding: 48px 40px;
    color: white;
    margin-bottom: 32px;
    text-align: center;
  }
  .hero-banner h1 { font-size: 2.4rem; font-weight: 700; margin: 0 0 12px; }
  .hero-banner p { font-size: 1.1rem; opacity: 0.9; margin: 0; }

  .card {
    background: white;
    border-radius: 12px;
    padding: 28px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    margin-bottom: 20px;
  }

  .severity-danger {
    background: #fef2f2;
    border-left: 4px solid #ef4444;
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 12px;
  }
  .severity-warning {
    background: #fffbeb;
    border-left: 4px solid #f59e0b;
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 12px;
  }
  .severity-advisory {
    background: #eff6ff;
    border-left: 4px solid #3b82f6;
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 12px;
  }

  .badge-danger  { background:#ef4444; color:white; padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:600; }
  .badge-warning { background:#f59e0b; color:white; padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:600; }
  .badge-advisory{ background:#3b82f6; color:white; padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:600; }

  .score-circle {
    width: 100px; height: 100px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.8rem; font-weight: 700; color: white;
    margin: 0 auto 16px;
  }

  .stat-box {
    background: white;
    border-radius: 10px;
    padding: 20px;
    text-align: center;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }
  .stat-number { font-size: 2rem; font-weight: 700; }
  .stat-label  { font-size: 0.85rem; color: #6b7280; margin-top: 4px; }

  .user-pill {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 24px;
    padding: 8px 16px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 0.9rem;
    color: #1e40af;
  }

  .plan-banner {
    background: linear-gradient(135deg, #059669 0%, #10b981 100%);
    border-radius: 10px;
    padding: 16px 24px;
    color: white;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  div[data-testid="stButton"] > button {
    border-radius: 8px;
    font-weight: 600;
    transition: all 0.2s;
  }

  footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ─── Secret Helper ───
def get_secret(key: str, default: str = "") -> str:
    try:
        val = st.secrets[key]
        if val and str(val).strip():
            return str(val).strip()
    except Exception:
        pass
    for section in ["general", "secrets", "app"]:
        try:
            val = st.secrets[section][key]
            if val and str(val).strip():
                return str(val).strip()
        except Exception:
            pass
    env_val = os.environ.get(key, "")
    if env_val:
        return env_val
    return default


# ─── Config ───
OPENAI_API_KEY   = get_secret("OPENAI_API_KEY")
SUPABASE_URL     = get_secret("SUPABASE_URL")
SUPABASE_KEY     = get_secret("SUPABASE_KEY")
PADDLE_VENDOR_ID = get_secret("PADDLE_VENDOR_ID")
PADDLE_PRODUCT_ID= get_secret("PADDLE_PRODUCT_ID", "pri_monthly_29")
ADMIN_EMAIL      = get_secret("ADMIN_EMAIL", "wisemanida6969@gmail.com")

_GC_PARTS = ["1027408584811", "jppotl63fg8nkhmeer95k12sq5a4hdd6"]
_GS_PARTS = ["GOCSPX", "1TPDCyHMlGghr3LOlSYax2kQNPXh"]
_DEFAULT_CID  = f"{_GC_PARTS[0]}-{_GC_PARTS[1]}.apps.googleusercontent.com"
_DEFAULT_SEC  = f"{_GS_PARTS[0]}-{_GS_PARTS[1]}"
_DEFAULT_RURI = "https://access.trytimeback.com/"

GOOGLE_CLIENT_ID     = get_secret("GOOGLE_CLIENT_ID", _DEFAULT_CID)
GOOGLE_CLIENT_SECRET = get_secret("GOOGLE_CLIENT_SECRET", _DEFAULT_SEC)
REDIRECT_URI         = get_secret("REDIRECT_URI", _DEFAULT_RURI)

# ─── Supabase ───
supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY and SUPABASE_URL != "YOUR_SUPABASE_URL":
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ══════════════════════════════════════
# Persistent Session (Mobile-safe)
# ══════════════════════════════════════
import hmac, hashlib, base64, time

SESSION_SECRET = get_secret("SESSION_SECRET", GOOGLE_CLIENT_SECRET or "fallback-secret-change-me")
SESSION_TTL    = 60 * 60 * 24 * 30  # 30 days

def create_session_token(user_info: dict) -> str:
    payload = {
        "email":   user_info.get("email", ""),
        "name":    user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
        "exp":     int(time.time()) + SESSION_TTL,
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64  = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    sig          = hmac.new(SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64      = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def verify_session_token(token: str):
    try:
        payload_b64, sig_b64 = token.split(".")
        expected     = hmac.new(SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
        expected_b64 = base64.urlsafe_b64encode(expected).decode().rstrip("=")
        if not hmac.compare_digest(sig_b64, expected_b64):
            return None
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def inject_session_save(token: str):
    """Save session token to localStorage so it survives mobile tab kills / cookie clears."""
    st.components.v1.html(f"""
        <script>
          try {{
            window.parent.localStorage.setItem('ac_session', {json.dumps(token)});
          }} catch(e) {{
            try {{ localStorage.setItem('ac_session', {json.dumps(token)}); }} catch(e2) {{}}
          }}
        </script>
    """, height=0)


def inject_session_restore():
    """If user has a stored session token but Streamlit session is empty, redirect with token in URL."""
    st.components.v1.html("""
        <script>
          (function() {
            try {
              const w = window.parent || window;
              const token = w.localStorage.getItem('ac_session');
              if (!token) return;
              const url = new URL(w.location.href);
              if (url.searchParams.get('auth')) return;
              if (url.searchParams.get('code'))  return;  // OAuth flow in progress
              url.searchParams.set('auth', token);
              w.location.replace(url.toString());
            } catch(e) {}
          })();
        </script>
    """, height=0)


def inject_session_clear():
    st.components.v1.html("""
        <script>
          try { window.parent.localStorage.removeItem('ac_session'); } catch(e) {
            try { localStorage.removeItem('ac_session'); } catch(e2) {}
          }
        </script>
    """, height=0)


# ══════════════════════════════════════
# Google OAuth
# ══════════════════════════════════════

def get_google_login_url() -> str:
    cid  = get_secret("GOOGLE_CLIENT_ID", _DEFAULT_CID)
    ruri = get_secret("REDIRECT_URI", _DEFAULT_RURI)
    st.session_state["_oauth_redirect_uri"] = ruri
    st.session_state["_oauth_client_id"]    = cid
    params = {
        "client_id":     cid,
        "redirect_uri":  ruri,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "offline",
        "prompt":        "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    cid     = st.session_state.get("_oauth_client_id", get_secret("GOOGLE_CLIENT_ID", _DEFAULT_CID))
    csecret = get_secret("GOOGLE_CLIENT_SECRET", _DEFAULT_SEC)
    ruri    = st.session_state.get("_oauth_redirect_uri", get_secret("REDIRECT_URI", _DEFAULT_RURI))
    payload = {
        "client_id":     cid,
        "client_secret": csecret,
        "code":          code,
        "grant_type":    "authorization_code",
        "redirect_uri":  ruri,
    }
    resp = requests.post("https://oauth2.googleapis.com/token", data=payload)
    if resp.status_code != 200:
        raise Exception(f"Token exchange failed ({resp.status_code}): {resp.text}")
    return resp.json()


def get_user_info(access_token: str) -> dict:
    resp = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    return resp.json()


def handle_oauth_callback():
    if st.session_state.get("login_error"):
        st.error(st.session_state["login_error"])
        st.session_state.pop("login_error", None)

    params = st.query_params

    # ── 1) Restore from persistent session token ──
    auth_token = params.get("auth")
    if auth_token and not st.session_state.get("logged_in"):
        payload = verify_session_token(auth_token)
        if payload:
            st.session_state["logged_in"] = True
            st.session_state["user_info"] = {
                "name":    payload.get("name", ""),
                "email":   payload.get("email", ""),
                "picture": payload.get("picture", ""),
            }
            st.query_params.clear()
            st.rerun()
        else:
            # Bad/expired token - clear it from storage
            inject_session_clear()
            st.query_params.clear()

    # ── 2) Fresh OAuth code from Google ──
    code = params.get("code")
    if code and not st.session_state.get("logged_in"):
        try:
            token_data = exchange_code_for_token(code)
            user_info  = get_user_info(token_data["access_token"])
            ui = {
                "name":    user_info.get("name", ""),
                "email":   user_info.get("email", ""),
                "picture": user_info.get("picture", ""),
            }
            st.session_state["logged_in"] = True
            st.session_state["user_info"] = ui
            # Persist to localStorage for mobile resilience
            inject_session_save(create_session_token(ui))
            st.query_params.clear()
            st.rerun()
        except Exception as e:
            st.session_state["login_error"] = f"Login failed: {e}"
            st.query_params.clear()
            st.rerun()


def logout():
    inject_session_clear()
    for k in ["logged_in", "user_info", "analysis_result", "last_url"]:
        st.session_state.pop(k, None)
    st.rerun()


# ══════════════════════════════════════
# Supabase Helpers
# ══════════════════════════════════════

def save_analysis(user_email: str, url: str, result: dict):
    if supabase:
        try:
            supabase.table("accessibility_reports").insert({
                "user_email":   user_email,
                "url":          url,
                "score":        result.get("score", 0),
                "total_issues": result.get("total_issues", 0),
                "result_json":  json.dumps(result),
                "created_at":   datetime.utcnow().isoformat(),
            }).execute()
            return
        except Exception:
            pass
    _sqlite_save_scan(user_email, url, result)


def load_reports(user_email: str) -> list:
    if supabase:
        try:
            resp = (
                supabase.table("accessibility_reports")
                .select("*")
                .eq("user_email", user_email)
                .order("created_at", desc=True)
                .limit(10)
                .execute()
            )
            return resp.data or []
        except Exception:
            pass
    return _sqlite_load_scans(user_email)


def count_scans_this_month(user_email: str) -> int:
    """Count how many scans the user has run since the 1st of the current UTC month."""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    if supabase:
        try:
            resp = (
                supabase.table("accessibility_reports")
                .select("id", count="exact")
                .eq("user_email", user_email)
                .gte("created_at", month_start)
                .execute()
            )
            return resp.count or 0
        except Exception:
            pass
    # SQLite fallback
    try:
        conn = sqlite3.connect(_SQLITE_DB)
        row = conn.execute(
            "SELECT COUNT(*) FROM scan_history WHERE user_email=? AND created_at >= ?",
            (user_email, month_start.replace("T", " ")),
        ).fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0


def check_subscription(user_email: str) -> bool:
    if user_email.lower() == ADMIN_EMAIL.lower():
        return True
    if supabase:
        try:
            resp = (
                supabase.table("subscriptions")
                .select("*")
                .eq("user_email", user_email)
                .eq("status", "active")
                .execute()
            )
            return len(resp.data or []) > 0
        except Exception:
            pass
    return _sqlite_is_pro(user_email)


# ══════════════════════════════════════
# Accessibility Analysis
# ══════════════════════════════════════

def fetch_page_content(url: str) -> tuple[str, str]:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.HTTPError as e:
        if e.response.status_code in (403, 429):
            raise ValueError(f"This site blocks automated access (HTTP {e.response.status_code}). Try a different URL such as https://example.com or https://trytimeback.com")
        raise
    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove scripts & styles to reduce tokens
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)[:6000]
    html_snippet = str(soup)[:8000]
    return text, html_snippet


ANALYSIS_PROMPT = """You are a professional web accessibility auditor specializing in WCAG 2.1/2.2 and ADA compliance.

Analyze the following webpage HTML and produce an actionable audit with copy-paste-ready fixes.

IMPORTANT: Respond entirely in English. All fields must be in English, regardless of the source language of the webpage.

Severity mapping:
- DANGER: Critical violations making content inaccessible (WCAG Level A failures, high legal risk)
- WARNING: Important usability issues (WCAG Level AA failures)
- ADVISORY: Best-practice improvements (WCAG Level AAA / polish)

Return a JSON object with this exact structure:
{
  "score": <integer 0-100, overall accessibility score>,
  "summary": "<2-3 sentence overall assessment>",
  "issues": [
    {
      "severity": "DANGER" | "WARNING" | "ADVISORY",
      "wcag_criterion": "<e.g. 1.1.1 Non-text Content>",
      "title": "<short violation name, e.g. 'Missing alt text on hero image'>",
      "description": "<what the issue is, 1-2 sentences>",
      "location": "<where in the page, e.g. 'Main navigation, 3rd link'>",
      "code_before": "<ACTUAL HTML element from the scanned page, copied verbatim. Must be the exact string that appears in the source. 1-5 lines, under 300 chars>",
      "code_after": "<Corrected HTML, copy-paste ready. Must be a drop-in replacement for code_before. Same structure, same attributes, only adding/fixing what is needed for compliance. 1-5 lines, under 300 chars>",
      "why": "<one sentence, under 20 words, explaining the real-world user impact>",
      "fix_time": "<realistic estimate: '1 minute', '2 minutes', '5 minutes', '15 minutes', '30 minutes'>"
    }
  ],
  "quick_wins": ["<top 3 easiest improvements, one line each>"],
  "positives": ["<good accessibility practices already present on the page>"]
}

STRICT RULES for code_before and code_after:
1. code_before MUST be copied VERBATIM from the HTML below. Do NOT invent, paraphrase, or write a generic placeholder like <img src="logo.png">. If you cannot find the exact element, skip the issue.
2. code_after MUST be the FIXED version of the SAME element — structure and attributes preserved, only the accessibility problem corrected.
3. Both snippets must be valid HTML that works as-is when pasted back into the page.
4. Never use ellipsis (...) or comments like <!-- existing code --> to abbreviate. Write the full element.
5. If the violation is page-level (missing <html lang>, no skip-link, etc.), code_before is the actual opening tag as found; code_after is that tag fixed.
6. Escape quotes properly for valid JSON (\\").
7. NEVER change the element type between code_before and code_after. If code_before is a text-only <a>Pactbug</a>, code_after must remain an <a> with text — do NOT replace it with <a><img></a>.
8. NEVER add new elements (img, svg, etc.) that did not exist in code_before. The fix is editing/adding ATTRIBUTES on existing elements, not introducing new HTML structure.

CRITICAL ANTI-HALLUCINATION RULES — read carefully:
A. Before flagging "missing alt text", verify that code_before ACTUALLY contains an <img>, <svg role="img">, <input type="image">, or <area> element. A text-only link like <a class="logo">BrandName</a> is NOT an image and does NOT require alt text — text inside the link IS the accessible name. Do NOT flag this.
B. Before flagging "missing label", verify that code_before contains an actual <input>, <textarea>, or <select> element. Don't flag <a>, <div>, <span> for missing labels.
C. Before flagging "low contrast", you must be able to see explicit color/background-color values. If colors aren't visible in the HTML (handled by external CSS), do NOT guess — skip the issue.
D. Before flagging "small target size", you must see explicit width/height. If sizes are external CSS, skip.
E. If you are unsure whether something is truly a violation, DO NOT include it. Quality over quantity. False positives confuse users.
F. The accessible name of a link or button can come from: visible text content, aria-label, aria-labelledby, alt on a child img, or title. If ANY of these exist, the element has an accessible name — do NOT flag it as empty/unlabeled.
G. NEVER flag "focus indicator missing" based on HTML alone. Focus styles live in CSS (:focus, :focus-visible). You cannot determine focus visibility from HTML. Browsers also provide default focus rings. Skip this issue unless you can SEE explicit `outline: none` or `outline: 0` in inline styles.
H. NEVER suggest inline `style="outline: ..."` as a focus fix. Inline styles are always-on; focus indicators must use CSS pseudo-classes (:focus-visible). If you can't write a proper CSS rule fix, skip the issue.
I. For "unclear link text" (WCAG 2.4.4), ONLY flag truly generic phrases: "click here", "here", "read more", "more", "link", "this", or empty links. Phrases that include a noun describing the destination ("Explore Our Products", "View Pricing", "Download Report", "Read the Guide") are CLEAR — do NOT flag them.
J. NEVER change the user-visible business copy as a "fix" (e.g., do not turn "Explore Our Products" into "Explore Our AI Products"). Accessibility fixes change attributes (alt, aria-*, role, lang, tabindex) or add hidden helper elements, NOT marketing wording.
K. If a fix would require external CSS that you cannot see (focus styles, contrast, hover states, target size), explicitly skip the issue rather than guessing inline-style hacks.
L. NEVER submit an issue where code_before and code_after are identical or differ only in whitespace. If you cannot produce a concrete attribute/structure change, the issue is not a real violation — skip it.
M. For "improper heading structure" / "heading order": ONLY flag if you can identify the SPECIFIC out-of-order or skipped level (e.g., page jumps from h1 to h3 with no h2). Provide a real before/after that fixes the level (h3→h2). Do NOT flag a single heading in isolation — heading structure is a multi-element concern.
N. For "skip link" suggestions: only propose `href="#X"` when an element with id="X" already exists in the HTML below. If no main/content landmark with an id is present, propose `<main id="main-content">` change instead, OR skip the issue. A skip link to a non-existent id is broken.
O. The TITLE of the issue must accurately match what code_before actually shows. Do not say "Missing alt text" if code_before contains no <img>. Do not say "Improper heading structure" if code_before contains a single, properly-leveled heading.
P. SEVERITY guardrails:
   - "Missing skip link" is at most ADVISORY. NEVER DANGER or WARNING. WCAG 2.4.1 is satisfied by landmarks (<main>, <nav>) which most modern sites have.
   - "Unclear link text" is at most ADVISORY. NEVER DANGER. It only escalates to WARNING for empty buttons/links with no accessible name at all.
   - "Improper heading order" is ADVISORY unless h1 is missing entirely.
   - DANGER (Level A failure, legal risk) is reserved for: missing alt on real <img>, form input with no label, empty button/link with no accessible name, missing <html lang>, autoplay audio without controls, keyboard trap.
Q. LOGO/BRAND link convention: A link containing only the brand/site name (e.g., <a>Pactbug</a>, <a>Apple</a>) pointing to home is a UNIVERSALLY UNDERSTOOD pattern. Do NOT flag this as "unclear link text". The brand name IS the accessible name and the destination is conventionally home.
R. NEVER change the `href` attribute as part of an accessibility fix. Changing where a link navigates is a BEHAVIORAL change, not an accessibility fix. Accessibility fixes affect attributes like aria-*, alt, role, lang — not href, src, or business logic.
S. Do NOT append explanatory suffixes like " - Home", " (link)", " (page)", " Website", " Page", " Site" to link text. If the visible text is already a real word/phrase (e.g., "Visit RedlineAI", "Read Documentation", "View Pricing"), it is sufficient. Only flag truly empty or placeholder text. Verbs like "Visit", "Read", "View", "Download", "Explore" combined with a proper noun = clear text. SKIP THE ISSUE.
T. SKIP-LINK strict requirement: A skip-link issue may be reported ONLY when ALL of these are true:
   1. The HTML has NO `<main>` element AND no `<nav>` with role="navigation" landmarks AND no aria-label="..." on regions.
   2. code_after MUST show TWO elements being added together: (a) the skip link itself, AND (b) the matching id="..." on the target main content element. Showing only one half is a broken fix.
   EXAMPLE of valid code_after (must be present in JSON, both parts):
     "<body>\\n  <a href=\\"#main-content\\" class=\\"skip-link\\">Skip to main content</a>\\n  <header>...existing...</header>\\n  <main id=\\"main-content\\">...existing main content...</main>\\n</body>"
   If you cannot show the matching id addition together with the skip link, OR if `<main>` already exists (even without an id), SKIP the issue. Browsers and screen readers can navigate by landmarks without explicit skip links.
U. FINAL CHECK before emitting any issue: re-read your code_before, code_after, title, and severity. If any rule A-T is violated, DELETE the issue from your response. The user prefers ZERO issues over WRONG issues.

WCAG 2.2 NEW CRITERIA — actively check for these (added in WCAG 2.2):

V. 2.4.11 Focus Not Obscured (Minimum) — Level AA:
   This issue exists ONLY when an element ALREADY has `position: sticky` or `position: fixed` IN code_before. You MUST see the actual sticky/fixed declaration in the HTML inline style or in a visible <style> tag.
   - DO NOT flag a plain `<nav>`, `<header>`, or `<footer>` without explicit sticky/fixed positioning.
   - DO NOT propose ADDING `position: sticky` as a fix — that CREATES the problem, not solves it.
   - Valid fix patterns: REMOVE the sticky positioning, or ADD `scroll-margin-top: <value>` to focusable children, or ensure z-index allows focus to remain visible.
   - If code_before has no sticky/fixed, SKIP the issue entirely.
   Severity: WARNING.

W. 2.5.7 Dragging Movements — Level AA:
   Any functionality that uses dragging (sliders, drag-to-reorder, swipe-to-dismiss) must have a single-pointer alternative (clicks, buttons). Flag elements with `draggable="true"`, slider inputs without buttons, or JS handlers like `ondragstart` that have no apparent click alternative. Severity: WARNING.

X. 3.2.6 Consistent Help — Level A:
   If help mechanisms appear (contact links, help chat, FAQ link, phone number), they must appear in the SAME relative order on every page. You cannot verify this from a single page scan, so DO NOT flag this — only mention in `positives` if you see help mechanisms present. Skip otherwise.

Y. 3.3.7 Redundant Entry — Level A:
   Forms must not require users to re-enter information they already provided in the same process (unless re-entry is essential, e.g. password confirmation). Flag form pages that have multiple fields asking for the same data (email twice on the same page outside of confirmation context, address re-entry). Severity: WARNING.

Z. 3.3.8 Accessible Authentication (Minimum) — Level AA:
   Authentication processes must NOT rely on cognitive function tests (transcribing characters from images, solving puzzles, remembering a username) without an alternative. Flag CAPTCHAs (image text, math puzzles, "select all bridges" type challenges), or login forms requiring memorization without password manager support (autocomplete="off" on password fields, paste disabled on password fields). Severity: DANGER for clearly inaccessible CAPTCHA without alternative; WARNING for autocomplete=off on auth fields.

Apply these rules to ALL violation types: missing alt text, low contrast, missing form labels, missing focus indicators, small target size, inaccessible authentication, missing heading structure, empty links/buttons, etc.

Webpage URL: {url}

HTML Content:
{html}

Return ONLY valid JSON, no markdown fences."""


def analyze_accessibility(url: str, html_snippet: str) -> dict:
    if not OPENAI_API_KEY:
        raise ValueError("OpenAI API key not configured")

    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = ANALYSIS_PROMPT.replace("{url}", url).replace("{html}", html_snippet)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=8000,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Attempt to salvage truncated JSON by closing it
        salvaged = raw.rstrip().rstrip(",")
        for suffix in ("]}", "\"]}", "}]}", "\"}]}"):
            try:
                result = json.loads(salvaged + suffix)
                break
            except json.JSONDecodeError:
                continue
        else:
            raise ValueError("AI returned invalid JSON. The page may be too complex. Try a simpler URL.")

    # Filter out hallucinated / low-quality issues
    raw_issues = result.get("issues", [])
    filtered = []
    for it in raw_issues:
        cb = (it.get("code_before") or "").strip()
        ca = (it.get("code_after") or "").strip()
        title = (it.get("title") or "").lower()
        wcag  = (it.get("wcag_criterion") or "").lower()

        # 1. Skip if before/after are identical (no real fix)
        if cb and ca and cb == ca:
            continue

        # 2. Skip-link issues: must include matching id="..." in code_after,
        #    AND the original page must have NO landmarks. Modern landmarked
        #    pages already satisfy WCAG 2.4.1 via screen-reader landmark navigation.
        is_skip_link_issue = "skip" in title or "bypass" in title or "2.4.1" in wcag
        if is_skip_link_issue:
            # If the page already has any landmark element, suppress the issue
            html_lower = html_snippet.lower()
            has_landmark = any(token in html_lower for token in [
                "<main", "role=\"main\"", "role='main'",
                "<nav", "role=\"navigation\"", "role='navigation'",
                "role=\"banner\"", "role=\"contentinfo\"", "role=\"complementary\"",
                "<header", "<footer", "<aside",
            ])
            if has_landmark:
                continue
            # Otherwise still require a complete fix
            href_match = re.search(r'href="#([\w\-]+)"', ca)
            if not href_match:
                continue
            target_id = href_match.group(1)
            if f'id="{target_id}"' not in ca:
                continue

        # 3. Focus indicator: reject inline `style="outline: ..."` hacks
        if "focus" in title and 'style="outline' in ca:
            continue

        # 4. Sticky/fixed obscured focus: require sticky/fixed in code_before
        if "obscur" in title or "2.4.11" in wcag:
            cb_lower = cb.lower()
            if "position: sticky" not in cb_lower and "position: fixed" not in cb_lower and "position:sticky" not in cb_lower and "position:fixed" not in cb_lower:
                continue

        # 5. Alt text on non-image element
        if "alt" in title and "<img" not in cb.lower() and "<svg" not in cb.lower() and "<input" not in cb.lower() and "<area" not in cb.lower():
            continue

        # 6. Reject suffix-padding "fixes" for link text
        if cb and ca and cb in ca:
            extra = ca.replace(cb, "").strip()
            if extra and any(suffix in extra.lower() for suffix in [" website", " page", " site", " - home", " (link)", " (page)"]):
                continue

        # 7. Heading structure: must show 2+ heading elements in code_before
        is_heading_issue = "heading" in title or "1.3.1" in wcag or "2.4.6" in wcag
        if is_heading_issue:
            heading_count_before = len(re.findall(r"<h[1-6][\s>]", cb, re.IGNORECASE))
            if heading_count_before < 2:
                continue
            # Don't allow inventing new heading text
            new_headings = re.findall(r"<h[1-6][^>]*>([^<]+)</h[1-6]>", ca, re.IGNORECASE)
            old_headings = re.findall(r"<h[1-6][^>]*>([^<]+)</h[1-6]>", cb, re.IGNORECASE)
            invented = [h for h in new_headings if h.strip() and h.strip() not in [o.strip() for o in old_headings]]
            if invented:
                continue

        # 8. Generic safeguard: code_after must not contain >40 chars of new visible text
        # that wasn't in code_before (catches fabricated content)
        text_before = re.sub(r"<[^>]+>", "", cb).strip()
        text_after  = re.sub(r"<[^>]+>", "", ca).strip()
        if text_after and text_before:
            # Find text in After that's not in Before
            extra_text = text_after
            for word in re.findall(r"\w+", text_before):
                extra_text = extra_text.replace(word, "", 1)
            if len(extra_text.strip()) > 40:
                # Likely invented content - allow only known safe additions
                safe_phrases = ["skip to main content", "skip to content"]
                if not any(p in extra_text.lower() for p in safe_phrases):
                    continue

        filtered.append(it)
    result["issues"] = filtered

    # Recompute counts after filtering
    result["danger_count"]   = sum(1 for i in filtered if i.get("severity") == "DANGER")
    result["warning_count"]  = sum(1 for i in filtered if i.get("severity") == "WARNING")
    result["advisory_count"] = sum(1 for i in filtered if i.get("severity") == "ADVISORY")

    # Normalize & enrich
    issues = result.get("issues", [])
    result["total_issues"]  = len(issues)
    result["danger_count"]  = sum(1 for i in issues if i.get("severity") == "DANGER")
    result["warning_count"] = sum(1 for i in issues if i.get("severity") == "WARNING")
    result["advisory_count"]= sum(1 for i in issues if i.get("severity") == "ADVISORY")
    result["analyzed_at"]   = datetime.utcnow().isoformat()
    result["url"]           = url
    return result


# ══════════════════════════════════════
# PDF Report Generator
# ══════════════════════════════════════

class AccessibilityPDF(FPDF):
    def header(self):
        self.set_fill_color(30, 64, 175)
        self.rect(0, 0, 210, 20, "F")
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 14)
        self.set_xy(0, 6)
        self.cell(0, 10, "AccessCheck AI - Accessibility Report", align="C")
        self.set_y(28)

    def footer(self):
        self.set_y(-15)
        self.set_text_color(150, 150, 150)
        self.set_font("Helvetica", "", 8)
        self.cell(0, 10, f"Generated by AccessCheck AI | access.trytimeback.com | Page {self.page_no()}", align="C")


def _pdf_safe(text: str, max_len: int = 2000) -> str:
    """Convert text to latin-1 safe string for FPDF default fonts.
    Truncates to max_len and inserts break points in long unbroken runs."""
    if text is None:
        return ""
    safe = str(text).encode("latin-1", "replace").decode("latin-1")
    if len(safe) > max_len:
        safe = safe[:max_len] + "..."
    # Insert space every 60 chars in unbroken runs to allow wrapping
    out = []
    run = 0
    for ch in safe:
        if ch.isspace():
            run = 0
            out.append(ch)
        else:
            if run >= 60:
                out.append(" ")
                run = 0
            out.append(ch)
            run += 1
    return "".join(out)


def _safe_multi_cell(pdf, w, h, text):
    """Wrapper that tries CHAR wrap mode if available, falls back gracefully."""
    try:
        pdf.multi_cell(w, h, text, new_x="LMARGIN", new_y="NEXT")
    except Exception:
        # Fallback: truncate aggressively and retry
        short = text[:300] if len(text) > 300 else text
        try:
            pdf.multi_cell(w, h, short)
        except Exception:
            pdf.cell(w or 180, h, short[:100], ln=True)


def generate_pdf(result: dict, user_email: str) -> bytes:
    pdf = AccessibilityPDF()
    pdf.set_top_margin(28)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_text_color(30, 30, 30)

    # Title block
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(30, 64, 175)
    pdf.cell(0, 10, "Website Accessibility Audit Report", ln=True)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    analyzed_at = result.get("analyzed_at", datetime.utcnow().isoformat())[:19].replace("T", " ")
    _safe_multi_cell(pdf, 0, 6, _pdf_safe(f"URL: {result.get('url', 'N/A')}"))
    pdf.cell(0, 6, _pdf_safe(f"Analyzed: {analyzed_at} UTC"), ln=True)
    pdf.cell(0, 6, _pdf_safe(f"Requested by: {user_email}"), ln=True)
    pdf.ln(6)

    # Score
    score = result.get("score", 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(30, 64, 175)
    pdf.cell(0, 8, f"Accessibility Score: {score}/100", ln=True)
    pdf.ln(3)

    # Stats
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(60, 7, f"Critical Issues: {result.get('danger_count', 0)}", border=1)
    pdf.cell(60, 7, f"Warnings: {result.get('warning_count', 0)}", border=1)
    pdf.cell(60, 7, f"Advisory: {result.get('advisory_count', 0)}", border=1)
    pdf.ln(10)

    # Summary
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 8, "Executive Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)
    summary = result.get("summary", "")
    _safe_multi_cell(pdf, 0, 6, _pdf_safe(summary))
    pdf.ln(5)

    # Issues
    severity_colors = {
        "DANGER":   (239, 68, 68),
        "WARNING":  (245, 158, 11),
        "ADVISORY": (59, 130, 246),
    }

    for severity_label in ["DANGER", "WARNING", "ADVISORY"]:
        issues = [i for i in result.get("issues", []) if i.get("severity") == severity_label]
        if not issues:
            continue

        pdf.set_font("Helvetica", "B", 12)
        r, g, b = severity_colors[severity_label]
        pdf.set_text_color(r, g, b)
        pdf.cell(0, 8, f"{severity_label} Issues ({len(issues)})", ln=True)
        pdf.set_text_color(30, 30, 30)

        for idx, issue in enumerate(issues, 1):
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(30, 30, 30)
            title = f"{idx}. {issue.get('title', '')} [{issue.get('wcag_criterion', '')}]"
            _safe_multi_cell(pdf, 0, 6, _pdf_safe(title))

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(80, 80, 80)
            _safe_multi_cell(pdf, 0, 5, _pdf_safe(f"Location: {issue.get('location', 'N/A')}"))
            _safe_multi_cell(pdf, 0, 5, _pdf_safe(f"Issue: {issue.get('description', '')}"))
            why_txt = issue.get("why", "")
            if why_txt:
                _safe_multi_cell(pdf, 0, 5, _pdf_safe(f"Why: {why_txt}"))
            ftime = issue.get("fix_time", "")
            if ftime:
                _safe_multi_cell(pdf, 0, 5, _pdf_safe(f"Fix time: {ftime}"))

            code_b = issue.get("code_before", "").strip()
            code_a = issue.get("code_after", "").strip()
            if code_b:
                pdf.set_font("Courier", "", 8)
                pdf.set_text_color(153, 27, 27)
                _safe_multi_cell(pdf, 0, 4, _pdf_safe(f"Before: {code_b}"))
            if code_a:
                pdf.set_font("Courier", "", 8)
                pdf.set_text_color(6, 95, 70)
                _safe_multi_cell(pdf, 0, 4, _pdf_safe(f"After:  {code_a}"))
            pdf.ln(3)

        pdf.ln(4)

    # Quick Wins
    quick_wins = result.get("quick_wins", [])
    if quick_wins:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 64, 175)
        pdf.cell(0, 8, "Quick Wins (Top Priorities)", ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 30, 30)
        for i, win in enumerate(quick_wins, 1):
            _safe_multi_cell(pdf, 0, 6, _pdf_safe(f"{i}. {win}"))
        pdf.ln(4)

    # Positives
    positives = result.get("positives", [])
    if positives:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(5, 150, 105)
        pdf.cell(0, 8, "What's Working Well", ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 30, 30)
        for pos in positives:
            _safe_multi_cell(pdf, 0, 6, _pdf_safe(f"- {pos}"))

    return bytes(pdf.output())


# ══════════════════════════════════════
# Paddle Payment Widget
# ══════════════════════════════════════

def render_paddle_checkout(user_email: str):
    vendor_id  = PADDLE_VENDOR_ID or "YOUR_PADDLE_VENDOR_ID"
    product_id = PADDLE_PRODUCT_ID

    paddle_html = f"""
    <script src="https://cdn.paddle.com/paddle/v2/paddle.js"></script>
    <script>
      Paddle.Initialize({{ token: '{vendor_id}' }});
    </script>
    <div style="text-align:center; padding: 24px;">
      <div style="background: linear-gradient(135deg,#1e40af,#3b82f6); border-radius:12px; padding:32px; color:white; max-width:400px; margin:0 auto;">
        <div style="font-size:2rem; font-weight:700; margin-bottom:4px;">$29<span style="font-size:1rem; font-weight:400;">/month</span></div>
        <div style="font-size:1.1rem; font-weight:600; margin-bottom:16px;">AccessCheck AI Pro</div>
        <ul style="text-align:left; list-style:none; padding:0; margin:0 0 24px; font-size:0.95rem;">
          <li style="padding:4px 0;">✅ Unlimited website scans</li>
          <li style="padding:4px 0;">✅ WCAG 2.2 / ADA compliance</li>
          <li style="padding:4px 0;">✅ PDF reports</li>
          <li style="padding:4px 0;">✅ AI-powered fix suggestions</li>
          <li style="padding:4px 0;">✅ Scan history</li>
          <li style="padding:4px 0;">✅ Priority support</li>
        </ul>
        <a href="#"
           onclick="Paddle.Checkout.open({{ items: [{{ priceId: '{product_id}', quantity: 1 }}], customer: {{ email: '{user_email}' }}, successCallback: function() {{ window.location.reload(); }} }}); return false;"
           style="display:block; background:white; color:#1e40af; font-weight:700; padding:14px 28px; border-radius:8px; text-decoration:none; font-size:1rem;">
          Subscribe Now →
        </a>
      </div>
    </div>
    """
    st.components.v1.html(paddle_html, height=420)


# ══════════════════════════════════════
# UI Components
# ══════════════════════════════════════

def render_hero():
    st.markdown("""
    <div class="hero-banner">
      <h1>♿ AccessCheck AI</h1>
      <p>Instant WCAG 2.2 & ADA Compliance Analysis — Powered by AI</p>
    </div>
    """, unsafe_allow_html=True)


def render_score_card(result: dict):
    score = result.get("score", 0)
    if score >= 80:
        color = "#059669"
        label = "Good"
    elif score >= 60:
        color = "#f59e0b"
        label = "Needs Work"
    else:
        color = "#ef4444"
        label = "Critical"

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="stat-box">
          <div class="stat-number" style="color:{color}">{score}</div>
          <div class="stat-label">Accessibility Score</div>
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="stat-box">
          <div class="stat-number" style="color:#ef4444">{result.get('danger_count',0)}</div>
          <div class="stat-label">Critical Issues</div>
        </div>""", unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="stat-box">
          <div class="stat-number" style="color:#f59e0b">{result.get('warning_count',0)}</div>
          <div class="stat-label">Warnings</div>
        </div>""", unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="stat-box">
          <div class="stat-number" style="color:#3b82f6">{result.get('advisory_count',0)}</div>
          <div class="stat-label">Advisory</div>
        </div>""", unsafe_allow_html=True)


def render_issues(result: dict):
    issues = result.get("issues", [])
    if not issues:
        st.success("No accessibility issues found!")
        return

    severity_order = ["DANGER", "WARNING", "ADVISORY"]
    severity_labels = {
        "DANGER":   ("🔴 Critical Issues",   "severity-danger",   "badge-danger"),
        "WARNING":  ("🟡 Warnings",          "severity-warning",  "badge-warning"),
        "ADVISORY": ("🔵 Advisory",          "severity-advisory", "badge-advisory"),
    }

    for sev in severity_order:
        filtered = [i for i in issues if i.get("severity") == sev]
        if not filtered:
            continue

        title, card_cls, badge_cls = severity_labels[sev]
        st.markdown(f"### {title} ({len(filtered)})")

        for idx, issue in enumerate(filtered):
            why       = issue.get("why", "") or issue.get("description", "")
            fix_time  = issue.get("fix_time", "").strip()
            st.markdown(f"""
            <div class="{card_cls}">
              <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px; flex-wrap:wrap;">
                <span class="{badge_cls}">{sev}</span>
                <strong style="font-size:0.95rem;">{issue.get('title','')}</strong>
                <span style="margin-left:auto; font-size:0.8rem; color:#6b7280;">{issue.get('wcag_criterion','')}</span>
              </div>
              <div style="font-size:0.85rem; color:#374151; margin-bottom:4px;">
                📍 <em>{issue.get('location','')}</em>
              </div>
              <div style="font-size:0.9rem; color:#374151; margin-bottom:8px;">
                {issue.get('description','')}
              </div>
              <div style="display:flex; gap:14px; font-size:0.85rem; color:#4b5563; margin-top:6px;">
                <div>💡 <strong>Why:</strong> {why}</div>
                {f'<div style="margin-left:auto;">⏱ <strong>Fix time:</strong> {fix_time}</div>' if fix_time else ''}
              </div>
            </div>
            """, unsafe_allow_html=True)

            code_before = issue.get("code_before", "").strip()
            code_after  = issue.get("code_after", "").strip()
            if code_before or code_after:
                with st.expander("👁️ View Before / After Code (copy-paste ready)", expanded=False):
                    col_b, col_a = st.columns(2)
                    with col_b:
                        st.markdown("**❌ Before (actual code from page)**")
                        st.code(code_before or "(not available)", language="html")
                    with col_a:
                        st.markdown("**✅ After (drop-in replacement)**")
                        st.code(code_after or "(not available)", language="html")


def render_positives_and_wins(result: dict):
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### ✅ What's Working Well")
        positives = result.get("positives", [])
        if positives:
            for pos in positives:
                st.markdown(f"""
                <div style="background:#f0fdf4; border-left:3px solid #22c55e; padding:10px 14px;
                            border-radius:6px; margin-bottom:8px; font-size:0.9rem; color:#166534;">
                  {pos}
                </div>""", unsafe_allow_html=True)
        else:
            st.info("No positives detected.")

    with col2:
        st.markdown("### ⚡ Quick Wins")
        quick_wins = result.get("quick_wins", [])
        if quick_wins:
            for i, win in enumerate(quick_wins, 1):
                st.markdown(f"""
                <div style="background:#eff6ff; border-left:3px solid #3b82f6; padding:10px 14px;
                            border-radius:6px; margin-bottom:8px; font-size:0.9rem; color:#1e40af;">
                  <strong>{i}.</strong> {win}
                </div>""", unsafe_allow_html=True)
        else:
            st.info("No quick wins identified.")


# ══════════════════════════════════════
# Main App
# ══════════════════════════════════════

LEGAL_PAGES = {
    "terms": {
        "title": "Terms of Service",
        "content": """
**This service is operated by Trytimeback.**

**Effective Date:** April 18, 2026
**Last Updated:** April 23, 2026

## 1. Acceptance of Terms
By accessing, signing into, or using AccessCheck AI (the "Service"), you ("User", "you") agree to be bound by these Terms of Service ("Terms"). If you do not agree with any part of these Terms, you must not access or use the Service. These Terms form a legally binding agreement between you and Trytimeback (the "Company", "we", "us").

## 2. Description of Service
AccessCheck AI is an automated website accessibility auditing tool that analyzes publicly accessible webpages against the Web Content Accessibility Guidelines (WCAG 2.1 / 2.2) and the Americans with Disabilities Act (ADA). The Service generates reports containing severity-ranked issues, suggested fixes, and before/after code snippets.

Reports produced by the Service are advisory in nature. They do not constitute a legal compliance certification, a substitute for a manual accessibility audit, or a guarantee of regulatory conformance in any jurisdiction.

## 3. Eligibility and User Accounts
- You must be at least 13 years of age to use the Service.
- You must sign in using a valid Google account.
- You are responsible for all activity occurring under your account.
- You agree to provide accurate, current, and complete information.
- You must not share account credentials or allow others to use your account.

## 4. Subscription Plans and Billing
- **Free plan:** Limited to 3 website scans per account, lifetime.
- **Pro plan:** USD $29.00 per month, billed monthly via Paddle.com Inc. ("Paddle"), our authorized reseller and merchant of record.
- Subscriptions renew automatically at the end of each billing cycle unless cancelled at least 24 hours before renewal.
- All prices are in United States Dollars (USD) and exclude applicable sales tax, VAT, or similar taxes, which are calculated and collected by Paddle.
- You authorize Paddle to charge the payment method on file for all recurring fees until you cancel.

## 5. Refund Policy
A 14-day refund policy applies to Pro subscriptions, in accordance with Paddle's terms of service. See the full [Refund Policy](?legal=refund) for details and how to submit a refund request.

## 6. Acceptable Use
You agree that you will NOT:
- Submit URLs for websites you do not own, operate, or have explicit permission to audit.
- Use the Service to scan, probe, or attempt to penetrate systems without authorization.
- Reverse-engineer, decompile, scrape, or attempt to extract the underlying AI models, prompts, or infrastructure.
- Use the Service in violation of any applicable local, state, national, or international law.
- Abuse, harass, or threaten other users or Trytimeback staff.
- Resell or redistribute Service output without written permission.

## 7. Intellectual Property
- All software, branding, and original content comprising the Service are the property of Trytimeback.
- AI-generated analysis reports produced for your account may be used by you for any lawful business purpose.
- You grant Trytimeback a limited license to process submitted URLs and page content solely for the purpose of providing the Service.

## 8. Third-Party Services
The Service integrates with third parties including Google (authentication), OpenAI (AI analysis), Paddle (payments), and Supabase (data storage). Use of the Service is also subject to their respective terms and privacy policies.

## 9. Disclaimer of Warranties
The Service is provided "AS IS" and "AS AVAILABLE" without warranties of any kind, express or implied, including but not limited to merchantability, fitness for a particular purpose, non-infringement, accuracy, or uninterrupted availability. Trytimeback does not warrant that analysis results are complete, error-free, or legally sufficient for ADA, WCAG, EAA, Section 508, or any other regulatory compliance.

## 10. Limitation of Liability
To the maximum extent permitted by law, Trytimeback, its officers, employees, affiliates, and licensors shall not be liable for any indirect, incidental, special, consequential, punitive, or exemplary damages, or for any loss of profits, revenue, data, goodwill, or business opportunities, arising from or related to your use of the Service. Our total aggregate liability for any claims relating to the Service shall not exceed the amount paid by you to Trytimeback in the twelve (12) months preceding the claim.

## 11. Indemnification
You agree to indemnify and hold harmless Trytimeback from any claims, damages, liabilities, and expenses (including reasonable attorneys' fees) arising from your misuse of the Service, violation of these Terms, or infringement of any third-party rights.

## 12. Termination
We may suspend or terminate your access to the Service at our sole discretion, with or without notice, for any violation of these Terms or for any conduct we believe to be harmful to Trytimeback, other users, or third parties. Upon termination, your right to use the Service ceases immediately; sections 7, 9, 10, 11, and 13 survive termination.

## 13. Governing Law and Disputes
These Terms are governed by the laws of the Republic of Korea, without regard to conflict-of-laws principles. Any dispute arising from the Service shall be resolved exclusively in the competent courts located in Changwon-si, Gyeongsangnam-do, Republic of Korea, unless another forum is required by mandatory consumer protection law.

## 14. Changes to the Terms
We reserve the right to update these Terms at any time. Material changes will be communicated by updating the "Last Updated" date above and, where appropriate, via email. Continued use of the Service after changes constitutes acceptance.

## 15. Contact
For questions, notices, or legal correspondence:
- **Email:** admin@trytimeback.com
- **Operator:** Trytimeback
""",
    },
    "privacy": {
        "title": "Privacy Policy",
        "content": """
**Effective Date:** April 18, 2026

## 1. Information We Collect
- **Account information:** Name and email address from Google OAuth login.
- **Usage data:** Website URLs you submit for analysis, scan results, and timestamps.
- **Payment data:** Processed by Paddle. We do not store credit card information.

## 2. How We Use Your Information
- To provide and improve the accessibility analysis Service.
- To manage your subscription and billing.
- To send service-related communications.
- We do not sell your personal data to third parties.

## 3. Data Storage
- Account and scan data is stored securely in Supabase.
- Scan results are retained for up to 90 days.

## 4. Third-Party Services
- **Google OAuth** — for authentication.
- **OpenAI** — for AI-powered analysis (URLs submitted are processed by OpenAI).
- **Paddle** — for payment processing.
- **Supabase** — for database storage.

## 5. Cookies
We use session cookies for authentication. No tracking or advertising cookies are used.

## 6. Your Rights
You have the right to:
- Access the personal data we hold about you.
- Request deletion of your account and data.
- Opt out of non-essential communications.

To exercise these rights, contact **admin@trytimeback.com**.

## 7. Data Security
We implement industry-standard security measures to protect your data.

## 8. Children's Privacy
The Service is not intended for users under 13 years of age.

## 9. Contact
For privacy inquiries: **admin@trytimeback.com**
""",
    },
    "cookies": {
        "title": "Cookie Policy",
        "content": """
**Effective Date:** April 18, 2026

## What Are Cookies?
Cookies are small text files stored on your device when you visit a website.

## Cookies We Use

| Cookie | Purpose | Duration |
|--------|---------|----------|
| Session cookie | Keeps you logged in | Session |
| Streamlit state | Maintains app state | Session |

## What We Don't Use
- We do **not** use advertising cookies.
- We do **not** use tracking or analytics cookies.
- We do **not** share cookie data with third parties.

## Managing Cookies
You can control cookies through your browser settings. Disabling session cookies will prevent you from logging in.

## Contact
For questions about our cookie use: **admin@trytimeback.com**
""",
    },
    "refund": {
        "title": "Refund Policy",
        "content": """
**This service is operated by Trytimeback.**

**Effective Date:** April 23, 2026

## Refund Policy

We offer a 14-day refund policy in accordance with Paddle's terms of service.

Customers may request a full refund within 14 days of purchase by contacting us at **admin@trytimeback.com**.

Refund requests after 14 days will be reviewed on a case-by-case basis.

## How to Request a Refund
Send an email to **admin@trytimeback.com** including:
- The email address associated with your AccessCheck AI account
- The date of purchase
- The Paddle order/transaction ID (found in your purchase receipt)
- A brief reason for the refund request (optional but appreciated)

Refunds are processed through Paddle and typically appear on your statement within 5–10 business days, depending on your payment provider.

## Cancellation vs. Refund
Cancelling your Pro subscription stops future billing but does not automatically issue a refund for the current period. If you cancel, you retain Pro access until the end of your current billing cycle. If you would also like a refund for the current period, you must request one separately as described above.

## Non-Refundable Items
- Renewal charges beyond the first 14 days are non-refundable unless required by law or approved on a case-by-case basis.
- Refunds cannot be issued for violations of our [Terms of Service](?legal=terms).

## Contact
For all refund-related inquiries: **admin@trytimeback.com**
""",
    },
    "accessibility": {
        "title": "Accessibility Statement",
        "content": """
**Effective Date:** April 18, 2026

## Our Commitment
AccessCheck AI is committed to ensuring digital accessibility for people with disabilities. We continually improve the user experience for everyone.

## Standards
We aim to conform to the **Web Content Accessibility Guidelines (WCAG) 2.2 Level AA**.

## Current Status
We are actively working to achieve and maintain WCAG 2.2 AA conformance. Known areas of improvement include:
- Enhanced keyboard navigation in analysis results
- Improved color contrast in data visualizations

## Technical Specifications
This website relies on the following technologies for conformance:
- HTML / CSS
- Python (Streamlit)
- WAI-ARIA

## Feedback
We welcome feedback on the accessibility of AccessCheck AI. If you experience barriers:

**Email:** admin@trytimeback.com
**Response time:** Within 2 business days

## Enforcement
If you are not satisfied with our response, you may contact the relevant disability authority in your jurisdiction.
""",
    },
}


def render_legal_page(page_key: str):
    page = LEGAL_PAGES.get(page_key)
    if not page:
        st.error("Page not found.")
        return

    if st.button("← Back to AccessCheck AI"):
        st.query_params.clear()
        st.rerun()

    st.markdown(f"# {page['title']}")
    st.markdown("---")
    st.markdown(page["content"])
    st.markdown("---")
    st.markdown("**Questions?** Contact us at [admin@trytimeback.com](mailto:admin@trytimeback.com)")


def main():
    handle_oauth_callback()

    # ─── Legal page routing ───
    legal_param = st.query_params.get("legal")
    if legal_param and legal_param in LEGAL_PAGES:
        render_legal_page(legal_param)
        return

    render_hero()

    # ─── Auth Check ───
    if not st.session_state.get("logged_in"):
        # Try to restore session from localStorage (mobile-safe)
        inject_session_restore()

        st.markdown("""
        <div class="card" style="max-width:520px; margin:0 auto; text-align:center;">
          <h2 style="color:#1e40af; margin-bottom:8px;">Get Started Free</h2>
          <p style="color:#6b7280; margin-bottom:24px;">
            Sign in with Google to analyze your website's accessibility.<br>
            First 3 scans free — Pro plan $29/month for unlimited scans.
          </p>
        """, unsafe_allow_html=True)

        login_url = get_google_login_url()
        st.markdown(f"""
          <a href="{login_url}" style="display:inline-block; background:#1e40af; color:white;
             font-weight:600; padding:14px 32px; border-radius:8px; text-decoration:none;
             font-size:1rem; margin-bottom:20px;">
            🔐 Sign in with Google
          </a>
        """, unsafe_allow_html=True)

        st.markdown("""
          <div style="color:#9ca3af; font-size:0.85rem;">
            By signing in, you agree to our Terms of Service
          </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("""
        <div style="text-align:center; padding:20px 0;">
          <h3 style="color:#374151;">What AccessCheck AI Analyzes</h3>
        </div>
        """, unsafe_allow_html=True)

        c1, c2, c3 = st.columns(3)
        features = [
            ("🖼️", "Alt Text & Images", "Checks all images for descriptive alt text per WCAG 1.1.1"),
            ("⌨️", "Keyboard Navigation", "Verifies all interactive elements are keyboard accessible"),
            ("🎨", "Color Contrast", "Ensures text meets 4.5:1 contrast ratio requirements"),
            ("📋", "Forms & Labels", "Checks form fields have proper labels and error messages"),
            ("🔗", "Links & Buttons", "Validates descriptive link text and button labels"),
            ("📱", "Screen Reader", "Tests ARIA roles, landmarks, and semantic HTML structure"),
        ]
        for col, (icon, title, desc) in zip([c1, c2, c3, c1, c2, c3], features):
            with col:
                st.markdown(f"""
                <div class="card" style="text-align:center; padding:20px;">
                  <div style="font-size:2rem; margin-bottom:8px;">{icon}</div>
                  <div style="font-weight:600; color:#1e40af; margin-bottom:6px;">{title}</div>
                  <div style="font-size:0.85rem; color:#6b7280;">{desc}</div>
                </div>""", unsafe_allow_html=True)

        # ─── Footer ───
        st.components.v1.html("""
        <div style="font-family:'Inter',sans-serif; margin-top:60px; border-top:1px solid #e5e7eb; padding-top:40px;">
          <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:32px; margin-bottom:40px;">

            <div style="min-width:200px;">
              <div style="font-weight:700; color:#1e40af; font-size:1.1rem; margin-bottom:12px;">&#9855; AccessCheck AI</div>
              <div style="color:#6b7280; font-size:0.88rem; line-height:1.7;">
                AI-powered WCAG 2.2 &amp; ADA<br>accessibility analysis tool.<br>
                Built for developers, designers,<br>and compliance teams.
              </div>
            </div>

            <div style="min-width:140px;">
              <div style="font-weight:600; color:#374151; margin-bottom:12px; font-size:0.9rem;">Product</div>
              <div style="display:flex; flex-direction:column; gap:8px; font-size:0.88rem; color:#6b7280;">
                <span>Features</span>
                <span>Pricing</span>
                <span>WCAG 2.2 Guide</span>
                <span>ADA Compliance</span>
              </div>
            </div>

            <div style="min-width:160px;">
              <div style="font-weight:600; color:#374151; margin-bottom:12px; font-size:0.9rem;">Legal</div>
              <div style="display:flex; flex-direction:column; gap:8px; font-size:0.88rem;">
                <a href="?legal=terms" style="color:#6b7280; text-decoration:none;">Terms of Service</a>
                <a href="?legal=privacy" style="color:#6b7280; text-decoration:none;">Privacy Policy</a>
                <a href="?legal=cookies" style="color:#6b7280; text-decoration:none;">Cookie Policy</a>
                <a href="?legal=refund" style="color:#6b7280; text-decoration:none;">Refund Policy</a>
                <a href="?legal=accessibility" style="color:#6b7280; text-decoration:none;">Accessibility Statement</a>
              </div>
            </div>

            <div style="min-width:200px;">
              <div style="font-weight:600; color:#374151; margin-bottom:12px; font-size:0.9rem;">Contact &amp; Support</div>
              <div style="display:flex; flex-direction:column; gap:8px; font-size:0.88rem; color:#6b7280;">
                <span>&#128231; <a href="mailto:admin@trytimeback.com" style="color:#1e40af; text-decoration:none;">admin@trytimeback.com</a></span>
                <span>Response within 24 hours</span>
                <span style="margin-top:6px; color:#374151; font-weight:500;">Part of Trytimeback</span>
                <span><a href="https://trytimeback.com" target="_blank" style="color:#1e40af; text-decoration:none;">trytimeback.com</a></span>
              </div>
            </div>

          </div>

          <div style="border-top:1px solid #f3f4f6; padding-top:20px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:12px; align-items:center;">
            <div style="color:#9ca3af; font-size:0.82rem;">
              &copy; 2026 AccessCheck AI &middot; All rights reserved &middot; Powered by Trytimeback
            </div>
            <div style="color:#9ca3af; font-size:0.82rem; display:flex; gap:12px; flex-wrap:wrap;">
              <a href="?legal=terms" style="color:#9ca3af; text-decoration:none;">Terms of Service</a>
              <span>&middot;</span>
              <a href="?legal=privacy" style="color:#9ca3af; text-decoration:none;">Privacy Policy</a>
              <span>&middot;</span>
              <a href="?legal=cookies" style="color:#9ca3af; text-decoration:none;">Cookie Policy</a>
              <span>&middot;</span>
              <a href="?legal=refund" style="color:#9ca3af; text-decoration:none;">Refund Policy</a>
            </div>
          </div>
        </div>
        """, height=320)
        return

    # ─── Logged In ───
    user_info  = st.session_state.get("user_info", {})
    user_email = user_info.get("email", "")
    user_name  = user_info.get("name", "User")
    is_pro     = check_subscription(user_email)

    # Header
    col_user, col_logout = st.columns([6, 1])
    with col_user:
        picture = user_info.get("picture", "")
        img_tag = f'<img src="{picture}" style="width:28px; height:28px; border-radius:50%;">' if picture else "👤"
        plan_badge = '<span style="background:#059669; color:white; padding:2px 8px; border-radius:10px; font-size:0.75rem; margin-left:8px;">PRO</span>' if is_pro else '<span style="background:#e5e7eb; color:#374151; padding:2px 8px; border-radius:10px; font-size:0.75rem; margin-left:8px;">FREE</span>'
        st.markdown(f'<div class="user-pill">{img_tag} {user_name} — {user_email}{plan_badge}</div>', unsafe_allow_html=True)
    with col_logout:
        if st.button("Logout", type="secondary"):
            logout()

    st.markdown("<br>", unsafe_allow_html=True)

    # ─── Tabs ───
    tab_analyze, tab_history, tab_upgrade = st.tabs(["🔍 Analyze", "📋 History", "⭐ Upgrade"])

    with tab_analyze:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("### Enter Website URL to Analyze")

        url_input = st.text_input(
            "Website URL",
            placeholder="https://example.com",
            label_visibility="collapsed",
        )

        col_btn, col_info = st.columns([2, 5])
        with col_btn:
            analyze_btn = st.button("🔍 Analyze Accessibility", type="primary", use_container_width=True)
        with col_info:
            if not is_pro:
                used = count_scans_this_month(user_email)
                remaining = max(0, 3 - used)
                st.markdown(f'<div style="padding:10px 0; color:#6b7280; font-size:0.9rem;">Free plan: {remaining}/3 scans remaining this month</div>', unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

        if analyze_btn and url_input:
            if not is_pro:
                used = count_scans_this_month(user_email)
                if used >= 3:
                    st.warning("⚠️ You've used all 3 free scans this month. Upgrade to Pro for unlimited scans, or wait until next month.")
                    st.stop()

            if not OPENAI_API_KEY:
                st.error("OpenAI API key not configured. Please add it to Streamlit secrets.")
                st.stop()

            with st.spinner("🔍 Fetching webpage content..."):
                try:
                    _, html_snippet = fetch_page_content(url_input)
                except Exception as e:
                    st.error(f"Failed to fetch URL: {e}")
                    st.stop()

            with st.spinner("🤖 AI is analyzing accessibility (WCAG 2.2)..."):
                try:
                    result = analyze_accessibility(url_input, html_snippet)
                except Exception as e:
                    st.error(f"Analysis failed: {e}")
                    st.stop()

            st.session_state["analysis_result"] = result
            st.session_state["last_url"] = url_input
            save_analysis(user_email, url_input, result)
            st.rerun()

        # ─── Show Results ───
        result = st.session_state.get("analysis_result")
        if result:
            last_url = st.session_state.get("last_url", "")
            st.markdown(f"### 📊 Results for: `{last_url}`")
            analyzed_at = result.get("analyzed_at", "")[:19].replace("T", " ")
            st.caption(f"Analyzed at {analyzed_at} UTC")

            render_score_card(result)
            st.markdown("<br>", unsafe_allow_html=True)

            # Summary
            summary = result.get("summary", "")
            if summary:
                st.markdown(f"""
                <div class="card">
                  <h4 style="color:#1e40af; margin:0 0 8px;">Executive Summary</h4>
                  <p style="color:#374151; margin:0;">{summary}</p>
                </div>""", unsafe_allow_html=True)

            render_issues(result)
            render_positives_and_wins(result)

            # PDF Download
            st.markdown("---")
            st.markdown("### 📄 Download Report")
            col_pdf, _ = st.columns([2, 5])
            with col_pdf:
                with st.spinner("Generating PDF..."):
                    try:
                        pdf_bytes = generate_pdf(result, user_email)
                        safe_url  = re.sub(r'[^\w\-]', '_', last_url.replace("https://", "").replace("http://", ""))[:40]
                        filename  = f"accessibility_report_{safe_url}_{datetime.now().strftime('%Y%m%d')}.pdf"
                        st.download_button(
                            label="⬇️ Download PDF Report",
                            data=pdf_bytes,
                            file_name=filename,
                            mime="application/pdf",
                            use_container_width=True,
                        )
                    except Exception as e:
                        st.error(f"PDF generation failed: {e}")

    with tab_history:
        st.markdown("### 📋 Past Analysis Reports")
        reports = load_reports(user_email)

        if not reports:
            st.info("No reports yet. Run your first accessibility analysis above.")
        else:
            for report in reports:
                score = report.get("score", 0)
                color = "#059669" if score >= 80 else "#f59e0b" if score >= 60 else "#ef4444"
                created = report.get("created_at", "")[:19].replace("T", " ")
                url     = report.get("url", "N/A")
                issues  = report.get("total_issues", 0)

                col_a, col_b, col_c = st.columns([5, 2, 2])
                with col_a:
                    st.markdown(f"**{url}**  \n<small style='color:#6b7280'>{created} UTC</small>", unsafe_allow_html=True)
                with col_b:
                    st.markdown(f"<div style='color:{color}; font-weight:700; font-size:1.1rem;'>{score}/100</div>", unsafe_allow_html=True)
                with col_c:
                    st.markdown(f"<div style='color:#6b7280'>{issues} issues</div>", unsafe_allow_html=True)

                # Re-load button
                raw_json = report.get("result_json")
                if raw_json:
                    try:
                        cached = json.loads(raw_json)
                        if st.button(f"Load Report", key=f"load_{report.get('id',url)}"):
                            st.session_state["analysis_result"] = cached
                            st.session_state["last_url"] = url
                            st.rerun()
                    except Exception:
                        pass
                st.divider()

    with tab_upgrade:
        is_admin = user_email.lower() == ADMIN_EMAIL.lower()

        if is_admin:
            st.info("🔧 Admin mode — Paddle checkout visible for testing")

        if is_pro and not is_admin:
            st.markdown("""
            <div style="background:linear-gradient(135deg,#059669,#10b981); border-radius:12px;
                        padding:24px; color:white; text-align:center; margin-bottom:32px;">
              <h2 style="margin:0 0 8px;">🎉 You're on Pro!</h2>
              <p style="margin:0; opacity:0.9;">You have unlimited scans, PDF reports, and full WCAG 2.2 analysis.</p>
            </div>""", unsafe_allow_html=True)

        st.markdown("""
        <div style="text-align:center; margin-bottom:32px;">
          <h2 style="color:#111827; font-size:1.8rem; margin-bottom:8px;">Simple, Transparent Pricing</h2>
          <p style="color:#6b7280; font-size:1rem;">Start free. Upgrade when you need more.</p>
        </div>
        """, unsafe_allow_html=True)

        vendor_id  = PADDLE_VENDOR_ID or "YOUR_PADDLE_VENDOR_ID"
        product_id = PADDLE_PRODUCT_ID

        col1, col2 = st.columns(2, gap="large")

        with col1:
            st.markdown("""
            <div style="background:white; border:1px solid #e5e7eb; border-radius:16px; padding:32px; height:100%;">
              <div style="margin-bottom:20px;">
                <div style="font-size:0.85rem; font-weight:600; color:#6b7280; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;">Free</div>
                <div style="font-size:2.4rem; font-weight:700; color:#111827;">$0<span style="font-size:1rem; font-weight:400; color:#6b7280;">/month</span></div>
                <div style="color:#6b7280; font-size:0.9rem; margin-top:4px;">Get started with no commitment</div>
              </div>
              <hr style="border:none; border-top:1px solid #f3f4f6; margin:20px 0;">
              <ul style="list-style:none; padding:0; margin:0 0 28px; display:flex; flex-direction:column; gap:12px;">
                <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:#374151;">
                  <span style="color:#22c55e; font-size:1.1rem;">✓</span> 3 website scans total
                </li>
                <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:#374151;">
                  <span style="color:#22c55e; font-size:1.1rem;">✓</span> WCAG 2.2 accessibility analysis
                </li>
                <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:#374151;">
                  <span style="color:#22c55e; font-size:1.1rem;">✓</span> PDF report download
                </li>
                <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:#374151;">
                  <span style="color:#22c55e; font-size:1.1rem;">✓</span> AI fix suggestions
                </li>
                <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:#9ca3af;">
                  <span style="color:#d1d5db; font-size:1.1rem;">✗</span> Scan history
                </li>
                <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:#9ca3af;">
                  <span style="color:#d1d5db; font-size:1.1rem;">✗</span> Priority support
                </li>
              </ul>
              <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:12px; text-align:center; color:#6b7280; font-size:0.9rem; font-weight:500;">
                Current Plan
              </div>
            </div>
            """, unsafe_allow_html=True)

        with col2:
            st.components.v1.html(f"""
            <script>
              function openPaddleCheckout() {{
                var url = '/app/static/checkout.html?token={vendor_id}&price={product_id}&email=' + encodeURIComponent('{user_email}');
                var popup = window.open(url, 'paddle_checkout', 'width=900,height=900,scrollbars=yes,resizable=yes');
                if (!popup) {{
                  alert('Please allow popups for this site to open checkout.');
                }}
                return false;
              }}
            </script>
            <div style="font-family:'Inter',sans-serif; background:linear-gradient(135deg,#1e40af 0%,#3b82f6 100%); border-radius:16px; padding:32px; position:relative; overflow:hidden;">
              <div style="position:absolute; top:-20px; right:-20px; width:120px; height:120px; background:rgba(255,255,255,0.06); border-radius:50%;"></div>
              <div style="position:absolute; bottom:-30px; left:-10px; width:80px; height:80px; background:rgba(255,255,255,0.06); border-radius:50%;"></div>
              <div style="position:relative; z-index:1;">
                <div style="display:inline-block; background:rgba(255,255,255,0.2); color:white; font-size:0.75rem; font-weight:600; padding:4px 12px; border-radius:20px; margin-bottom:16px; letter-spacing:0.05em;">MOST POPULAR</div>
                <div style="font-size:0.85rem; font-weight:600; color:rgba(255,255,255,0.7); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;">Pro</div>
                <div style="font-size:2.4rem; font-weight:700; color:white;">$29<span style="font-size:1rem; font-weight:400; opacity:0.8;">/month</span></div>
                <div style="color:rgba(255,255,255,0.75); font-size:0.9rem; margin-top:4px; margin-bottom:20px;">Everything you need for compliance</div>
                <hr style="border:none; border-top:1px solid rgba(255,255,255,0.2); margin:20px 0;">
                <ul style="list-style:none; padding:0; margin:0 0 28px; display:flex; flex-direction:column; gap:12px;">
                  <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:white;">
                    <span style="background:rgba(255,255,255,0.2); border-radius:50%; width:20px; height:20px; display:inline-flex; align-items:center; justify-content:center; font-size:0.75rem; flex-shrink:0;">&#10003;</span>
                    <strong>Unlimited</strong>&nbsp;website scans
                  </li>
                  <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:white;">
                    <span style="background:rgba(255,255,255,0.2); border-radius:50%; width:20px; height:20px; display:inline-flex; align-items:center; justify-content:center; font-size:0.75rem; flex-shrink:0;">&#10003;</span>
                    Full WCAG 2.2 / ADA analysis
                  </li>
                  <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:white;">
                    <span style="background:rgba(255,255,255,0.2); border-radius:50%; width:20px; height:20px; display:inline-flex; align-items:center; justify-content:center; font-size:0.75rem; flex-shrink:0;">&#10003;</span>
                    Detailed PDF reports
                  </li>
                  <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:white;">
                    <span style="background:rgba(255,255,255,0.2); border-radius:50%; width:20px; height:20px; display:inline-flex; align-items:center; justify-content:center; font-size:0.75rem; flex-shrink:0;">&#10003;</span>
                    AI-powered fix suggestions
                  </li>
                  <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:white;">
                    <span style="background:rgba(255,255,255,0.2); border-radius:50%; width:20px; height:20px; display:inline-flex; align-items:center; justify-content:center; font-size:0.75rem; flex-shrink:0;">&#10003;</span>
                    Scan history (last 10 reports)
                  </li>
                  <li style="display:flex; align-items:center; gap:10px; font-size:0.95rem; color:white;">
                    <span style="background:rgba(255,255,255,0.2); border-radius:50%; width:20px; height:20px; display:inline-flex; align-items:center; justify-content:center; font-size:0.75rem; flex-shrink:0;">&#10003;</span>
                    Priority support
                  </li>
                </ul>
                <a href="#"
                   onclick="return openPaddleCheckout();"
                   style="display:block; background:white; color:#1e40af; font-weight:700; padding:16px; border-radius:10px; text-decoration:none; font-size:1rem; text-align:center; cursor:pointer;">
                  Upgrade to Pro &#8594;
                </a>
                <div style="text-align:center; margin-top:12px; color:rgba(255,255,255,0.6); font-size:0.8rem;">
                  Cancel anytime &middot; Secure payment by Paddle
                </div>
              </div>
            </div>
            """, height=560)


if __name__ == "__main__":
    main()
