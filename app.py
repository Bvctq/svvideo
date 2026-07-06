import os
import re
from urllib.parse import quote, unquote, urlparse

import requests
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS

app = Flask(__name__)

# Domain của trang PHP (123host) được phép gọi API này.
# Đặt biến môi trường ALLOWED_ORIGIN trên Render (dạng: https://tenmien.com hoặc
# nhiều domain cách nhau bởi dấu phẩy). Nếu chưa set, mặc định mở cho mọi domain (*)
# để dễ test lúc đầu -- nhớ giới hạn lại khi đã có domain thật, tránh trang khác
# "xài ké" băng thông tải video của bạn.
_origins_env = os.environ.get("ALLOWED_ORIGIN", "").strip()
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()] or "*"
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125 Safari/537.36"
    ),
    "Referer": "https://svxtract.com/",
}


def sanitize_filename(name: str) -> str:
    name = name or "video"
    name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    return name[:80] or "video"


@app.get("/")
def health():
    # Endpoint đơn giản để kiểm tra backend đã sống, và để các request
    # "ping giữ ấm" (xem README) có chỗ để gọi vào.
    return jsonify({"status": "ok"})


@app.post("/api/fetch-video")
def fetch_video():
    data = request.get_json(silent=True) or {}
    shopee_url_raw = (data.get("shopeeUrl") or "").strip()
    csrf_token_raw = (data.get("csrfToken") or "").strip()

    if not shopee_url_raw or not csrf_token_raw:
        return jsonify({"error": "Thiếu link Shopee hoặc csrf_token."}), 400

    # Chuẩn hoá: nếu người dùng lỡ dán giá trị ĐÃ url-encode (copy từ thanh địa chỉ
    # thay vì từ ô Query String Parameters đã decode sẵn của DevTools), unquote()
    # sẽ giải mã nó về dạng gốc; nếu giá trị đã ở dạng thường thì unquote() không
    # làm gì cả. Nhờ vậy tránh bị encode 2 lần (ví dụ %3A thành %253A).
    shopee_url = unquote(shopee_url_raw)
    csrf_token = unquote(csrf_token_raw)

    api_url = (
        "https://svxtract.com/apiv3.php?"
        f"url={quote(shopee_url, safe='')}&csrf_token={quote(csrf_token, safe='')}"
    )

    try:
        upstream = requests.get(api_url, headers=BROWSER_HEADERS, timeout=15)
    except requests.RequestException as exc:
        app.logger.warning("fetch-video request error: %s", exc)
        return jsonify({"error": "Không kết nối được tới nguồn video. Thử lại sau."}), 500

    if not upstream.ok:
        body_preview = upstream.text[:400]
        app.logger.warning("upstream %s error, body: %s", upstream.status_code, body_preview)
        return jsonify({
            "error": f"Nguồn trả lỗi (HTTP {upstream.status_code}).",
            # Trả kèm nội dung lỗi thật từ svxtract.com để debug nguyên nhân
            # chính xác (session/cookie, IP, token dùng 1 lần...) thay vì đoán.
            # Có thể bỏ field này khi mọi thứ đã chạy ổn, tránh lộ chi tiết ra UI công khai.
            "upstream_status": upstream.status_code,
            "upstream_body": body_preview,
        }), 502

    try:
        payload = upstream.json()
    except ValueError:
        return jsonify({"error": "Nguồn trả về dữ liệu không hợp lệ (không phải JSON)."}), 502

    if not payload.get("stream"):
        return jsonify({"error": "Không nhận được dữ liệu video hợp lệ từ nguồn."}), 502

    return jsonify(payload)


@app.get("/api/download")
def download():
    """Proxy tải file video, ép trình duyệt lưu file (Content-Disposition).

    LƯU Ý: route này stream toàn bộ file video qua server Python, phù hợp với
    Render (server chạy liên tục, không giới hạn dung lượng response) nhưng
    KHÔNG chạy được đúng trên Vercel (Vercel Functions giới hạn cứng 4.5MB mỗi
    response, hầu hết video sẽ vượt mức này). Nếu deploy trên Vercel, bỏ qua
    route này và cho nút tải trỏ thẳng tới link "stream" gốc từ svxtract.com.
    """
    url = request.args.get("url")
    filename = request.args.get("filename", "video")

    if not url:
        return "Thiếu url", 400

    host = urlparse(url).hostname
    if host != "svxtract.com":
        return "Chỉ cho phép tải từ svxtract.com", 400

    try:
        upstream = requests.get(url, headers=BROWSER_HEADERS, stream=True, timeout=30)
    except requests.RequestException:
        return "Lỗi khi tải video.", 500

    if not upstream.ok:
        return "Không tải được video từ nguồn.", 502

    def generate():
        for chunk in upstream.iter_content(chunk_size=65536):
            yield chunk

    headers = {
        "Content-Disposition": f'attachment; filename="{sanitize_filename(filename)}.mp4"',
        "Content-Type": upstream.headers.get("content-type", "video/mp4"),
    }
    return Response(stream_with_context(generate()), headers=headers)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
