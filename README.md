# Kiến trúc: Backend Python (Render) + Giao diện PHP (123host)

```
frontend-123host/index.php   →  upload lên 123host (chỉ cần PHP, không cần Node/Python)
backend-render/               →  đẩy lên Render, chạy Flask (Python), gọi API svxtract.com hộ
```

Vì frontend và backend giờ nằm ở **2 domain khác nhau**, trình duyệt sẽ gọi thẳng
từ JS trên trang PHP sang domain Render → đây là **cross-origin request**, nên
backend Python bắt buộc phải bật CORS cho domain của trang PHP (đã làm sẵn bằng
`flask-cors`, xem mục Cấu hình bên dưới).

## Vì sao chọn Render thay vì Vercel cho phần proxy tải video

Đã tra cứu kỹ trước khi trả lời phần này vì số liệu hay đổi:

- **Vercel Functions giới hạn cứng 4.5MB cho response** (kể cả Hobby lẫn Pro) —
  vượt mức này server trả lỗi `413 FUNCTION_PAYLOAD_TOO_LARGE`. Một video ~50
  giây, nhất là bản 1080p/1920p, gần như chắc chắn vượt 4.5MB. Nghĩa là route
  `/api/download` (proxy tải file, ép trình duyệt lưu) **sẽ không chạy được
  trên Vercel** cho video thật, chỉ demo được với file rất nhỏ.
- **Render** là server chạy liên tục (không phải serverless function), không
  có giới hạn dung lượng response kiểu đó, nên proxy-tải-file hoạt động bình
  thường. Đánh đổi: gói free của Render **spin-down sau 15 phút không có
  request**, lần gọi kế tiếp mất khoảng 30–60 giây để khởi động lại (đã có ghi
  chú việc này trong giao diện PHP).

→ Vì bạn cần tính năng tải file (không chỉ lấy JSON), **Render là lựa chọn phù
hợp hơn** cho toàn bộ backend này.

**Nếu vẫn muốn dùng Vercel:** vẫn dùng được cho route `/api/fetch-video` (chỉ
trả JSON nhỏ, không vấn đề gì). Với bước tải file thật sự, bỏ route
`/api/download` và cho nút "Tải xuống" trỏ thẳng vào link `stream` gốc từ
svxtract.com (video sẽ chảy thẳng từ CDN của họ về máy người dùng, không qua
Vercel nên không dính giới hạn 4.5MB) — đánh đổi là mất phần ép filename đẹp
qua `Content-Disposition`, và có thể bị chặn nếu CDN đó kiểm tra Referer chặt.
Nói mình biết nếu muốn bản chỉnh cho Vercel theo hướng này.

## 1. Deploy backend lên Render

1. Đẩy thư mục `backend-render/` lên một repo GitHub.
2. Trên Render: **New → Web Service** → chọn repo đó.
   - Runtime: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn --bind 0.0.0.0:$PORT app:app`
   - Instance Type: Free
   (Có sẵn `render.yaml` nếu muốn deploy bằng Blueprint cho nhanh.)
3. Sau khi deploy xong, Render cho một URL dạng `https://ten-app.onrender.com`.
   Test bằng cách mở URL đó — thấy `{"status":"ok"}` là backend đã sống.
4. Vào tab **Environment** của service, thêm biến:
   - `ALLOWED_ORIGIN` = domain trang PHP của bạn trên 123host, ví dụ
     `https://tenmien-cua-ban.com` (nhiều domain thì cách nhau bằng dấu phẩy).
     Nếu bỏ trống, mặc định mở cho mọi domain (`*`) — tiện để test lúc đầu
     nhưng nên giới hạn lại sau, tránh trang khác gọi ké API và ăn băng thông
     Render của bạn.

## 2. Deploy frontend lên 123host

1. Mở `frontend-123host/index.php`, sửa dòng đầu:
   ```php
   $API_BASE = "https://ten-app.onrender.com";
   ```
   thành đúng URL Render ở bước trên.
2. Upload file này lên 123host qua File Manager/FTP như một trang PHP bình
   thường (không cần cấu hình gì thêm, 123host chỉ cần chạy được PHP là đủ).

## 3. Lấy "url" và "csrf_token"

Giữ nguyên như trước — token này chưa tự động hoá được, lấy thủ công qua
DevTools trên svxtract.com. Chi tiết cách lấy đã ghi ngay trong giao diện
PHP (phần gợi ý dưới ô nhập token).

## 4. Lưu ý

- API svxtract.com không chính thức, có thể đổi/ngừng hoạt động bất cứ lúc
  nào không báo trước.
- Video vẫn thuộc về gian hàng đã đăng — hợp lý nhất là dùng để lưu video cá
  nhân; nếu định public hoá cho nhiều người dùng/tải hàng loạt thì nên cân
  nhắc thêm bản quyền và điều khoản của Shopee lẫn svxtract.com.
- Bản này chưa có rate-limit hay xác thực người dùng ở tầng API — hợp với quy
  mô cá nhân hơn là mở public không giới hạn.
