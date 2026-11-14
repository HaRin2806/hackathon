# Sketch2Banner — Web + Backend

Phác thảo tay + ảnh sản phẩm thật + brief → AI đọc bố cục → **3 banner PNG 1080×1080** (A bám phác thảo, B tối giản, C nhấn ưu đãi).
Tuỳ chọn: gắn **dịp lịch sử** ("Ngày này năm xưa") lấy từ bộ sự kiện chọn lọc + dataset `minhxthanh/Vietnam-History-1M-Vi` (MIT).

> Rubric tiêu chí 1 yêu cầu app trên **điện thoại Android thật**. Bản web dùng **chung backend/API** với app Android:
> web để thử nhanh và thu bằng chứng người dùng; app Android là bản demo chính.

## Chạy nhanh (5 phút)

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # điền AI_PROVIDER + AI_API_KEY
python scripts/make_samples.py   # tạo ảnh mẫu (phác thảo trái/phải + ảnh sản phẩm)
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Mở http://localhost:8000 → giao diện web. Kiểm tra end-to-end:

```bash
python scripts/smoke_test.py --base http://127.0.0.1:8000
python scripts/smoke_test.py --base http://127.0.0.1:8000 --sketch samples/sketch_product_right.jpg   # test T02
```

Mỗi lượt ghi vào `backend/evidence/runs.csv` (job_id, model, upload/ai/render/total ms) + PNG + job.json, dùng làm bằng chứng.

**Chế độ không cần key:** `AI_PROVIDER=mock` trả bố cục mẫu để dev UI/renderer. Mọi kết quả mock đều gắn nhãn
**FIXTURE — không phải AI** trên giao diện và có `is_fixture=true` trong API. Không dùng mock khi demo.

### HTTPS cho điện thoại

```bash
cloudflared tunnel --url http://localhost:8000      # -> https://xxxx.trycloudflare.com
```

Web: mở URL tunnel trên điện thoại. Android: dùng URL này làm `BASE_URL`. URL tunnel đổi mỗi lần khởi động lại,
nên đặt BASE_URL ở chỗ sửa được trong app. Giữ laptop thức và cắm sạc.

## App Android (bản demo chính): `android/`

Kotlin + Jetpack Compose, minSdk 26, đã nhắm cho Redmi Note 13 Pro 5G (Android 13/14, HyperOS). Gồm:
Photo Picker cho 2 ảnh (copy ngay vào bộ nhớ app), form brief, gắn dịp lịch sử, gọi API, poll theo stage khi app đang mở,
3 thẻ A/B/C, xem PNG lớn, **lưu vào thư viện ảnh (Pictures/Sketch2Banner)**, **chia sẻ file PNG qua Sharesheet**.
Đóng hẳn app rồi mở lại vẫn tiếp tục đúng job đang chạy (job_id/token lưu trong SharedPreferences, request_id lưu trước khi POST).
Nút **Server** dùng để đổi BASE_URL ngay trong app.

**Build APK** (chọn 1 cách):
1. **GitHub Actions** (khuyên dùng vì mạng hội trường chậm): push repo lên GitHub → tab Actions → `android-apk` →
   tải artifact `sketch2banner-apk` (file `app-debug.apk`). Đổi URL mặc định bằng repo variable `S2B_BASE_URL`.
2. **Android Studio** (máy đã cài sẵn SDK): File → Open → thư mục `android/` → cắm điện thoại → Run.

**Cài lên Redmi (HyperOS):**
- Cài từ file APK: mở file → cho phép "Cài đặt ứng dụng không rõ nguồn gốc" cho trình quản lý file / Zalo.
- Cài qua USB từ Android Studio: Cài đặt → Giới thiệu điện thoại → chạm 7 lần vào "Phiên bản OS" → Tuỳ chọn nhà phát triển →
  bật **Gỡ lỗi USB** và **Cài đặt qua USB** (Xiaomi yêu cầu đăng nhập Mi account và có SIM).
- Để demo ổn định: Cài đặt → Ứng dụng → Sketch2Banner → Tiết kiệm pin → **Không hạn chế**.

**Kết nối điện thoại → laptop qua Wi-Fi LAN:** điện thoại và laptop dùng chung Wi-Fi. Chạy backend với `--host 0.0.0.0`,
mở cổng 8000 trên Windows Firewall (PowerShell admin:
`New-NetFirewallRule -DisplayName "Sketch2Banner 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`),
rồi trong app bấm Server → `http://<IPv4 laptop>:8000` (lệnh `ipconfig`). Wi-Fi hội trường thường chặn các máy nhìn thấy nhau;
khi đó dùng hotspot từ điện thoại khác hoặc tunnel HTTPS.

## Cấu hình AI (`backend/.env`)

| AI_PROVIDER | Endpoint (OpenAI-compatible) | Model mặc định |
|---|---|---|
| `gemini` | generativelanguage.googleapis.com/v1beta/openai | `gemini-2.5-flash` |
| `openai` | api.openai.com/v1 | `gpt-5.4-mini` |
| `deepseek` | api.deepseek.com | `deepseek-chat` (kiểm tra model có nhận ảnh không) |

Đổi model bằng `AI_MODEL`. API key chỉ nằm trên server, không bao giờ nằm trong APK hay bundle web.
Adapter dùng pattern của P-110 (`vlm_mass.py`): đặt schema trong prompt, bật `json_object`, validate bằng Pydantic,
retry tối đa 1 lần, không log prompt/ảnh/key.

## API (hợp đồng chung web + Android)

| Endpoint | Ghi chú |
|---|---|
| `POST /v1/generations` | multipart: `sketch`, `product`, `brief_json`, `client_request_id` → `202 {job_id, job_token, status}`. Cùng request_id + cùng payload → cùng job; khác payload → `409` |
| `GET /v1/generations/{id}` | header `X-Job-Token` (hoặc `?token=`). Trả status/stage/error_code/variants/metrics/layout_reading/is_fixture |
| `GET /v1/generations/{id}/variants/{A\|B\|C}.png` | PNG 1080×1080 |
| `GET /v1/generations/{id}/variants/{A\|B\|C}/thumbnail` | JPEG 360px |
| `GET /v1/history/events?q=&month_day=MM-DD` | tìm sự kiện lịch sử |
| `GET /health` | provider, model, key đã cấu hình chưa, số sự kiện |

`brief_json`: `{"product_name": "...", "headline": "", "price": "39.000đ", "cta": "Đặt ngay", "history_event_id": null}`.
Bắt buộc `product_name` và `cta`. Để trống `headline` thì AI gợi ý và UI ghi rõ "Tiêu đề do AI gợi ý".

Vòng đời job: `QUEUED → ANALYZING → VALIDATING → RENDERING → SUCCEEDED | FAILED`. Mỗi job lưu bền trong
`backend/data/jobs/{job_id}/`. Nếu backend restart, job đang chạy chuyển sang `INTERRUPTED`.
Mã lỗi AI gồm `ai_not_configured`, `ai_auth`, `ai_model_not_found`, `ai_rate_limited`, `ai_timeout`, `ai_bad_output`, `ai_refused`.

## Cấu trúc

```
backend/app/
  config.py       cấu hình (.env), preset provider
  schemas.py      Brief, DesignSpec v1
  ai_adapter.py   1 lần gọi multimodal → layout + 3 variants
  validator.py    clamp bbox, chống chồng lấn, sửa tương phản, bù variant thiếu (ghi lại trong spec.repairs)
  renderer.py     Pillow: ảnh gốc (contain), font tiếng Việt, fit chữ, card/plain/badge, PNG + thumbnail
  jobs.py         job store dạng file + worker nền, idempotency
  history.py      tìm sự kiện lịch sử
  main.py         FastAPI + phục vụ web tại /
backend/scripts/
  make_samples.py            ảnh test
  smoke_test.py              E2E + ghi evidence/runs.csv
  build_history_events.py    trích sự kiện từ dataset HF (streaming, bỏ trùng)
backend/data/history_events.json   21 sự kiện chọn lọc (verified) + phần trích từ dataset (verified=false)
web/   index.html, styles.css, app.js — HTML/JS thuần, không cần build
```

## Dataset lịch sử

```bash
python scripts/build_history_events.py --max-rows 20000     # lấy mẫu qua HTTP
python scripts/build_history_events.py --local "path/Vietnam History Complete.jsonl"   # file đã tải
```

Dataset là hỏi–đáp tổng hợp theo mẫu: cùng một sự kiện lặp lại với nhiều cách hỏi, và có chỗ sai năm.
Script đọc dạng streaming, dùng regex lấy `event / year / summary / significance`, bỏ trùng, chỉ giữ sự kiện xuất hiện ≥ 2 lần.
Các mục này mang nhãn `verified=false` ("chưa kiểm chứng" trên UI). Sự kiện chọn lọc luôn được ưu tiên.
Không fine-tune: model chỉ nhận tóm tắt sự kiện làm ngữ cảnh để viết tiêu đề; năm và tên sự kiện được vẽ trực tiếp từ dữ liệu.

## Giới hạn đã biết

- Chưa có app Android (dùng đúng API ở trên). Chưa có tách nền; ảnh sản phẩm được đặt trong photo card.
- Bố cục MVP gồm 4 vùng (headline / product / price / cta), chỉ khổ vuông 1080.
- Thời gian phản hồi thực tế chưa đo với key thật; xem `evidence/runs.csv` sau khi chạy.
