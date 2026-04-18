import streamlit as st
import os
import json
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

APP_VERSION = "2026-04-18-v1"

# ─── Page Config ───
st.set_page_config(
    page_title="AccessCheck AI | WCAG Accessibility Analyzer",
    page_icon="♿",
    layout="wide",
    initial_sidebar_state="collapsed",
)

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
    code   = params.get("code")
    if code and not st.session_state.get("logged_in"):
        try:
            token_data = exchange_code_for_token(code)
            user_info  = get_user_info(token_data["access_token"])
            st.session_state["logged_in"] = True
            st.session_state["user_info"] = {
                "name":    user_info.get("name", ""),
                "email":   user_info.get("email", ""),
                "picture": user_info.get("picture", ""),
            }
            st.query_params.clear()
            st.rerun()
        except Exception as e:
            st.session_state["login_error"] = f"Login failed: {e}"
            st.query_params.clear()
            st.rerun()


def logout():
    for k in ["logged_in", "user_info", "analysis_result", "last_url"]:
        st.session_state.pop(k, None)
    st.rerun()


# ══════════════════════════════════════
# Supabase Helpers
# ══════════════════════════════════════

def save_analysis(user_email: str, url: str, result: dict):
    if not supabase:
        return
    try:
        supabase.table("accessibility_reports").insert({
            "user_email":   user_email,
            "url":          url,
            "score":        result.get("score", 0),
            "total_issues": result.get("total_issues", 0),
            "result_json":  json.dumps(result),
            "created_at":   datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        pass


def load_reports(user_email: str) -> list:
    if not supabase:
        return []
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
        return []


def check_subscription(user_email: str) -> bool:
    if not supabase:
        return False
    if user_email.lower() == ADMIN_EMAIL.lower():
        return True
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
        return False


# ══════════════════════════════════════
# Accessibility Analysis
# ══════════════════════════════════════

def fetch_page_content(url: str) -> tuple[str, str]:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove scripts & styles to reduce tokens
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)[:6000]
    html_snippet = str(soup)[:8000]
    return text, html_snippet


ANALYSIS_PROMPT = """You are a professional web accessibility auditor specializing in WCAG 2.1 and ADA compliance.

Analyze the following webpage HTML/text content and provide a comprehensive accessibility report.

For each issue found, classify it as:
- DANGER: Critical violations that make content inaccessible (WCAG Level A failures)
- WARNING: Important issues affecting usability (WCAG Level AA failures)
- ADVISORY: Best practice improvements (WCAG Level AAA / general improvements)

Return a JSON object with this exact structure:
{
  "score": <integer 0-100, overall accessibility score>,
  "summary": "<2-3 sentence overall assessment>",
  "issues": [
    {
      "severity": "DANGER" | "WARNING" | "ADVISORY",
      "wcag_criterion": "<e.g. 1.1.1 Non-text Content>",
      "title": "<short issue title>",
      "description": "<what the issue is>",
      "location": "<where in the page, e.g. 'Navigation menu', 'Hero image'>",
      "fix": "<specific, actionable fix instruction with code example if relevant>"
    }
  ],
  "quick_wins": ["<top 3 easiest improvements>"],
  "positives": ["<list of good accessibility practices found>"]
}

Webpage URL: {url}

HTML Content:
{html}

Return ONLY valid JSON, no markdown fences."""


def analyze_accessibility(url: str, html_snippet: str) -> dict:
    if not OPENAI_API_KEY:
        raise ValueError("OpenAI API key not configured")

    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = ANALYSIS_PROMPT.format(url=url, html=html_snippet)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=4000,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    result = json.loads(raw)

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
        self.cell(0, 20, "AccessCheck AI - Accessibility Report", align="C")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_text_color(150, 150, 150)
        self.set_font("Helvetica", "", 8)
        self.cell(0, 10, f"Generated by AccessCheck AI | access.trytimeback.com | Page {self.page_no()}", align="C")


def generate_pdf(result: dict, user_email: str) -> bytes:
    pdf = AccessibilityPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_text_color(30, 30, 30)

    # Title block
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(30, 64, 175)
    pdf.ln(8)
    pdf.cell(0, 10, "Website Accessibility Audit Report", ln=True)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    analyzed_at = result.get("analyzed_at", datetime.utcnow().isoformat())[:19].replace("T", " ")
    pdf.cell(0, 6, f"URL: {result.get('url', 'N/A')}", ln=True)
    pdf.cell(0, 6, f"Analyzed: {analyzed_at} UTC", ln=True)
    pdf.cell(0, 6, f"Requested by: {user_email}", ln=True)
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
    pdf.multi_cell(0, 6, summary)
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
            pdf.multi_cell(0, 6, title)

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(80, 80, 80)
            pdf.multi_cell(0, 5, f"Location: {issue.get('location', 'N/A')}")
            pdf.multi_cell(0, 5, f"Issue: {issue.get('description', '')}")

            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(30, 100, 50)
            pdf.multi_cell(0, 5, f"Fix: {issue.get('fix', '')}")
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
            pdf.multi_cell(0, 6, f"{i}. {win}")
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
            pdf.multi_cell(0, 6, f"✓ {pos}")

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
          <li style="padding:4px 0;">✅ WCAG 2.1 / ADA compliance</li>
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
      <p>Instant WCAG 2.1 & ADA Compliance Analysis — Powered by AI</p>
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

        for issue in filtered:
            st.markdown(f"""
            <div class="{card_cls}">
              <div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">
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
              <div style="font-size:0.88rem; background:rgba(255,255,255,0.7); border-radius:6px; padding:10px;">
                🔧 <strong>Fix:</strong> {issue.get('fix','')}
              </div>
            </div>
            """, unsafe_allow_html=True)


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
**Effective Date:** April 18, 2026

## 1. Acceptance of Terms
By accessing or using AccessCheck AI ("Service"), you agree to be bound by these Terms of Service. If you do not agree, please do not use the Service.

## 2. Description of Service
AccessCheck AI provides AI-powered website accessibility analysis based on WCAG 2.1 and ADA guidelines. Results are advisory in nature and do not constitute legal compliance certification.

## 3. User Accounts
- You must sign in with a valid Google account.
- You are responsible for maintaining the confidentiality of your account.
- You must provide accurate information when using the Service.

## 4. Subscription and Billing
- Free plan: 3 website scans total.
- Pro plan: $29/month, billed monthly via Paddle.
- Subscriptions auto-renew unless cancelled before the renewal date.
- All prices are in USD and exclude applicable taxes.

## 5. Refund Policy
We offer a 7-day refund policy for Pro subscriptions. To request a refund, contact admin@trytimeback.com within 7 days of purchase.

## 6. Prohibited Use
You may not use the Service to:
- Scan websites you do not own or have permission to analyze.
- Attempt to reverse-engineer or misuse the AI analysis system.
- Violate any applicable laws or regulations.

## 7. Disclaimer of Warranties
The Service is provided "as is" without warranties of any kind. AccessCheck AI does not guarantee that analysis results are complete, accurate, or legally sufficient for ADA/WCAG compliance.

## 8. Limitation of Liability
AccessCheck AI shall not be liable for any indirect, incidental, or consequential damages arising from use of the Service.

## 9. Changes to Terms
We reserve the right to modify these Terms at any time. Continued use of the Service constitutes acceptance of updated Terms.

## 10. Contact
For questions about these Terms, contact us at **admin@trytimeback.com**.
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
**Effective Date:** April 18, 2026

## 7-Day Money-Back Guarantee
We offer a full refund within **7 days** of your initial Pro subscription purchase, no questions asked.

## Eligibility
- Refund requests must be submitted within 7 days of purchase.
- Only first-time Pro subscribers are eligible for the money-back guarantee.
- Subsequent billing cycles are non-refundable.

## How to Request a Refund
Email **admin@trytimeback.com** with:
- Your account email address
- Date of purchase
- Reason for refund (optional)

We will process your refund within 5-7 business days.

## Cancellation
You may cancel your Pro subscription at any time. Cancellation stops future billing but does not automatically trigger a refund. Cancelled accounts retain Pro access until the end of the current billing period.

## Contact
For refund requests: **admin@trytimeback.com**
""",
    },
    "accessibility": {
        "title": "Accessibility Statement",
        "content": """
**Effective Date:** April 18, 2026

## Our Commitment
AccessCheck AI is committed to ensuring digital accessibility for people with disabilities. We continually improve the user experience for everyone.

## Standards
We aim to conform to the **Web Content Accessibility Guidelines (WCAG) 2.1 Level AA**.

## Current Status
We are actively working to achieve and maintain WCAG 2.1 AA conformance. Known areas of improvement include:
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
                AI-powered WCAG 2.1 &amp; ADA<br>accessibility analysis tool.<br>
                Built for developers, designers,<br>and compliance teams.
              </div>
            </div>

            <div style="min-width:140px;">
              <div style="font-weight:600; color:#374151; margin-bottom:12px; font-size:0.9rem;">Product</div>
              <div style="display:flex; flex-direction:column; gap:8px; font-size:0.88rem; color:#6b7280;">
                <span>Features</span>
                <span>Pricing</span>
                <span>WCAG 2.1 Guide</span>
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
                reports = load_reports(user_email)
                remaining = max(0, 3 - len(reports))
                st.markdown(f'<div style="padding:10px 0; color:#6b7280; font-size:0.9rem;">Free plan: {remaining}/3 scans remaining</div>', unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

        if analyze_btn and url_input:
            if not is_pro:
                reports = load_reports(user_email)
                if len(reports) >= 3:
                    st.warning("⚠️ You've used all 3 free scans. Upgrade to Pro for unlimited scans.")
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

            with st.spinner("🤖 AI is analyzing accessibility (WCAG 2.1)..."):
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
              <p style="margin:0; opacity:0.9;">You have unlimited scans, PDF reports, and full WCAG 2.1 analysis.</p>
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
                  <span style="color:#22c55e; font-size:1.1rem;">✓</span> WCAG 2.1 accessibility analysis
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
                    Full WCAG 2.1 / ADA analysis
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
