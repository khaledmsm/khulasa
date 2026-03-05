"""
╔══════════════════════════════════════════════╗
║  Khulasa — خلاصة  Backend Server             ║
║  Serves the PWA + handles AI summarization   ║
╚══════════════════════════════════════════════╝

This single server does everything:
  1. Serves the PWA files (so you can access it on your iPhone)
  2. Handles /summarize API for AI-powered content summaries
  3. Works on your local network (MacBook → iPhone)

Usage:
  export ANTHROPIC_API_KEY="your-key"
  python server.py

Then on your iPhone:
  1. Open Safari → http://YOUR_MAC_IP:8080
  2. Tap Share → Add to Home Screen
  3. Done! You have a Khulasa app icon on your iPhone
"""

import os
import json
import re
import asyncio
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
import threading
import socket

# Try to import optional dependencies
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    print("⚠️  anthropic not installed. Summaries will use placeholder text.")
    print("   Install with: pip install anthropic")

try:
    from bs4 import BeautifulSoup
    import urllib.request
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    print("⚠️  beautifulsoup4 not installed. Content extraction will be basic.")
    print("   Install with: pip install beautifulsoup4")


# ─── Config ───────────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 8080))
PWA_DIR = Path(__file__).parent  # Serve files from same directory
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


# ─── Content Extraction ──────────────────────────────────────────
def extract_content(url: str) -> dict:
    """Fetch and extract text from a URL."""
    platform = "Other"
    if "tiktok" in url.lower(): platform = "TikTok"
    elif "twitter.com" in url.lower() or "x.com" in url.lower(): platform = "X"
    elif "reddit.com" in url.lower(): platform = "Reddit"
    elif "youtube.com" in url.lower() or "youtu.be" in url.lower(): platform = "YouTube"
    elif "instagram.com" in url.lower(): platform = "Instagram"

    if not HAS_BS4:
        return {"title": f"Link from {platform}", "text": f"URL: {url}", "platform": platform, "url": url}

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            title = soup.title.string if soup.title else "Untitled"
            text = soup.get_text(separator="\n", strip=True)[:3000]
            return {"title": title.strip()[:100], "text": text, "platform": platform, "url": url}
    except Exception as e:
        print(f"  ⚠️ Error fetching {url}: {e}")
        return {"title": f"Link from {platform}", "text": f"URL: {url}", "platform": platform, "url": url}


# ─── AI Summarization ────────────────────────────────────────────
def summarize_content(content: dict) -> dict:
    """Generate bilingual summary using Claude."""
    if not HAS_ANTHROPIC or not ANTHROPIC_API_KEY:
        return {
            "title_clean": content["title"],
            "summary_en": "Backend is running but no ANTHROPIC_API_KEY set. Set it and restart.",
            "summary_ar": "الخادم يعمل لكن لم يتم تعيين مفتاح API. قم بتعيينه وأعد التشغيل.",
            "content_type": "link",
            "read_time_original": "?",
            "read_time_summary": "~1 min",
        }

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Summarize this content in TWO languages. Be concise and focus on key takeaways.

URL: {content['url']}
Platform: {content['platform']}
Title: {content['title']}
Content:
{content['text']}

Respond ONLY with this JSON (no markdown, no extra text):
{{
  "title_clean": "Clean descriptive title in English",
  "summary_en": "Clear English summary in 3-5 sentences with key takeaways.",
  "summary_ar": "ملخص واضح بالعربي في ٣-٥ جمل مع النقاط الرئيسية.",
  "content_type": "video|thread|post|article",
  "read_time_original": "estimated original time",
  "read_time_summary": "time to read summary"
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250514",  # or "claude-3-5-sonnet-20241022" if this fails
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text
        text = re.sub(r"```json\s*|```", "", text).strip()
        return json.loads(text)
    except Exception as e:
        error_msg = str(e)
        print(f"  ⚠️ Summarization error: {error_msg}")
        
        # Give helpful error messages
        if "credit" in error_msg.lower() or "billing" in error_msg.lower():
            en_msg = "Anthropic API needs credit. Add funds at console.anthropic.com/billing"
            ar_msg = "API يحتاج رصيد. أضف رصيد في console.anthropic.com/billing"
        elif "invalid" in error_msg.lower() and "key" in error_msg.lower():
            en_msg = "Invalid API key. Check ANTHROPIC_API_KEY in Render environment variables."
            ar_msg = "مفتاح API غير صالح. تحقق من المتغيرات في Render."
        elif "model" in error_msg.lower():
            en_msg = "Model not available. Updating..."
            ar_msg = "النموذج غير متاح. جاري التحديث..."
        else:
            en_msg = f"Error: {error_msg[:150]}"
            ar_msg = "حدث خطأ في إنشاء الملخص. حاول مرة أخرى."
        
        return {
            "title_clean": content["title"],
            "summary_en": en_msg,
            "summary_ar": ar_msg,
            "content_type": "link",
            "read_time_original": "?",
            "read_time_summary": "~1 min",
        }


# ─── HTTP Server ──────────────────────────────────────────────────
class KhulasaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PWA_DIR), **kwargs)

    def do_GET(self):
        # Handle favicon requests gracefully
        if self.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return
        return super().do_GET()

    def do_POST(self):
        if self.path == "/summarize":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            url = data.get("url", "")

            print(f"\n📎 Processing: {url}")

            # Extract
            content = extract_content(url)
            print(f"  📄 Title: {content['title']}")
            print(f"  📍 Platform: {content['platform']}")

            # Summarize
            summary = summarize_content(content)
            print(f"  ✅ Summarized!")

            # Build response
            result = {
                "title": summary.get("title_clean", content["title"]),
                "platform": content["platform"],
                "summaryEn": summary.get("summary_en", ""),
                "summaryAr": summary.get("summary_ar", ""),
                "contentType": summary.get("content_type", "link"),
                "readTime": summary.get("read_time_summary", "~1 min"),
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
            return

        self.send_error(404)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        """Quieter logging — only show non-static requests."""
        try:
            if args and isinstance(args[0], str):
                path = args[0].split()[1] if " " in args[0] else args[0]
                if path.startswith("/summarize") or path == "/":
                    super().log_message(format, *args)
            else:
                super().log_message(format, *args)
        except Exception:
            pass


# ─── Get Local IP ─────────────────────────────────────────────────
def get_local_ip():
    """Get the Mac's local network IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"


# ─── Main ─────────────────────────────────────────────────────────
def main():
    local_ip = get_local_ip()

    print(f"""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   خلاصة — Khulasa Server Running!                        ║
║                                                          ║
║   On your MacBook:  http://localhost:{PORT}                ║
║   On your iPhone:   http://{local_ip}:{PORT}           ║
║                                                          ║
║   📱 To install as iPhone app:                           ║
║      1. Open the iPhone URL in Safari                    ║
║      2. Tap Share button (⬆️)                            ║
║      3. Tap "Add to Home Screen"                         ║
║      4. Done! Khulasa is now an app on your phone        ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
    """)

    if not ANTHROPIC_API_KEY:
        print("⚠️  No ANTHROPIC_API_KEY set. Summaries won't work.")
        print("   Run: export ANTHROPIC_API_KEY='your-key'\n")

    server = HTTPServer(("0.0.0.0", PORT), KhulasaHandler)
    print(f"🚀 Server listening on port {PORT}...\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
