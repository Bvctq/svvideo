import os
import re
from urllib.parse import quote, urlparse

# Sử dụng curl_cffi để giả lập TLS fingerprint của trình duyệt thật, vượt Cloudflare
from curl_cffi import requests as cffi_requests
from curl_cffi.requests import RequestsError
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS

app = Flask(__name__)

_origins_env = os.environ.get("ALLOWED_ORIGIN", "").strip()
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()] or "*"
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})

BROWSER_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://svxtract.com/",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


def sanitize_filename(name: str) -> str:
    name = name or "video"
    name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    return name[:80] or "video"


@app.get("/")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/fetch-video")
def fetch_video():
    data = request.get_json(silent=True) or {}
    shopee_url = data.get("shopeeUrl")
    csrf_token = data.get("csrfToken")

    if not shopee_url or not csrf_token:
        return jsonify({"error": "Thiếu link Shopee hoặc csrf_token."}), 400

    api_url = (
        "https://svxtract.com/apiv3.php?"
        f"url={quote(shopee_url, safe='')}&csrf_token={quote(csrf_token, safe='')}"
    )

    try:
        # Thêm impersonate="chrome124" để vượt Cloudflare TLS Fingerprint
        upstream = cffi_requests.get(
            api_url, 
            headers=BROWSER_HEADERS, 
            impersonate="chrome124", 
            timeout=20
        )
    except RequestsError as exc:
        app.logger.warning("fetch-video request error: %s", exc)
        return jsonify({"error": "Không kết nối được tới nguồn video. Thử lại sau."}), 500

    if not upstream.ok:
        return jsonify({
            "error": f"Nguồn trả lỗi (HTTP {upstream.status_code}). Bị Cloudflare chặn hoặc Token hết hạn."
        }), 502

    try:
        payload = upstream.json()
    except ValueError:
        return jsonify({"error": "Nguồn trả về dữ liệu không hợp lệ (có thể dính trang thử thách Captcha của Cloudflare)."}), 502

    if not payload.get("stream"):
        return jsonify({"error": "Không nhận được dữ liệu video hợp lệ từ nguồn."}), 502

    return jsonify(payload)


@app.get("/api/download")
def download():
    url = request.args.get("url")
    filename = request.args.get("filename", "video")

    if not url:
        return "Thiếu url", 400

    host = urlparse(url).hostname
    if host != "svxtract.com":
        return "Chỉ cho phép tải từ svxtract.com", 400

    try:
        upstream = cffi_requests.get(
            url, 
            headers=BROWSER_HEADERS, 
            impersonate="chrome124",
            stream=True, 
            timeout=30
        )
    except RequestsError:
        return "Lỗi khi tải video.", 500

    if not upstream.ok:
        return "Không tải được video từ nguồn.", 502

    def generate():
        for chunk in upstream.iter_content(chunk_size=65536):
            if chunk:
                yield chunk

    headers = {
        "Content-Disposition": f'attachment; filename="{sanitize_filename(filename)}.mp4"',
        "Content-Type": upstream.headers.get("content-type", "video/mp4"),
    }
    return Response(stream_with_context(generate()), headers=headers)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
