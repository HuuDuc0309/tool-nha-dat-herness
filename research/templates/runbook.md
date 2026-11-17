# Thu thập dữ liệu nhà đất cho thuê — hướng dẫn vận hành

Tài liệu cho phần mới thêm (`crawler`, `adapters`, `exporter`, `verify`, `regression`).
Quy trình tổng quát nằm trong `CLAUDE.md` và skill `/bat-dau-tim-du-lieu`.

## Kiến trúc

```
config/sites.json                     danh sách site + category + platform
config/property-fields.json           schema field (label tiếng Việt + key kỹ thuật)
src/property_tool/
  discover.py                         discovery-first (artifact website)
  orchestrator.py                     4 phase browser + discovery gate
  crawler.py                          crawl listing → detail → record + evidence
  verify.py                           kiểm tra schema/bằng chứng/mâu thuẫn
  exporter.py                         xuất Excel nhiều sheet
  regression.py                       test parser trên snapshot (offline)
  adapters/
    batdongsan_group.py               template cũ: batdongsan365.vn (+ card listing dùng chung)
    batdongsan_vn.py                  template mới re__pr-*: batdongsan.com.vn
research/sites/<site-id>/             artifact: template.md, integration.yaml, discovery.json
research/jobs/<job>/                  crawl-result.json, verification.json, snapshots/
Temp/                                 browser profile, log, script thử (gitignored)
```

## Luồng chạy chuẩn

```powershell
# 1. Discovery (bắt buộc với site mới / artifact cũ)
.\.venv\Scripts\python.exe -m src.property_tool.orchestrator "https://site/" --max-pages 20

# 2. Crawl. --headed để human giải Cloudflare; headless chỉ dùng khi site không chặn
.\.venv\Scripts\python.exe -m src.property_tool.crawler `
    --out research\jobs\<job> `
    --max-listing-pages 3 --max-details 400 --delay 1.5 `
    --headed --wait-human 300

# 3. Verify (schema + evidence + mâu thuẫn)
.\.venv\Scripts\python.exe -m src.property_tool.verify research\jobs\<job>

# 4. Export Excel
.\.venv\Scripts\python.exe -m src.property_tool.exporter research\jobs\<job>

# 5. Regression trên snapshot đã lưu (không cần mạng)
.\.venv\Scripts\python.exe -m src.property_tool.regression
```

## Ý nghĩa các tham số giới hạn

| Tham số | Ý nghĩa |
|---|---|
| `--max-listing-pages N` | **mỗi category** lấy tối đa N trang listing (không phải toàn site) |
| `--max-details N` | tổng số trang detail tối đa **mỗi site** |
| `--delay S` | nghỉ S giây giữa request (mặc định 1.5) |
| `--headed` | mở browser có cửa sổ để human giải challenge |
| `--wait-human N` | chờ tối đa N giây cho mỗi lần giải |

## Quy tắc dữ liệu (đã cài trong code)

### Không bao giờ bịa giá trị
- Field thiếu → chuỗi rỗng + dòng trong sheet `Chưa xác định`. Không điền `0`/`false`.
- `rent_period` chỉ được set khi **nguyên văn giá** có `/tháng`, `/năm`, `/ngày`.
  Không mặc định "tháng" (sai 12 lần nếu thực tế là năm).
- Số điện thoại bị site che (`0901 821 ***`) được lưu nguyên văn +
  `contact_masked=yes` + warning. Tool **không** bấm "Hiện số".

### Giá thuê: `rent_amount` chỉ là tổng giá tháng
| Tình huống | `rent_amount` | Field khác | Cảnh báo |
|---|---|---|---|
| `30 triệu/tháng` | `30000000` | — | không |
| `65 nghìn/m²` | rỗng | `price_per_m2_vnd=65000` | giá theo m² |
| `Thỏa thuận` | rỗng | — | giá thoả thuận |
| `1 nghìn` kèm `10/m²` | rỗng | — | giá không đủ tin cậy |

### Diện tích: giữ nguyên cái site hiển thị, đánh dấu mâu thuẫn
- `usable_area_m2` = "Diện tích" trên trang chi tiết.
- `factory_area_m2` / `land_area_m2` lấy từ **mô tả** khi có nhãn rõ
  ("diện tích xưởng", "diện tích khuôn viên", "kho xưởng").
- Trang nêu nhiều diện tích (500/700/1000/2000) → giá trị có thể là `"500; 700; 1000"`
  và `area_conflict` ghi rõ danh sách; `confidence` bị hạ ≤ 0.6;
  `extraction_status` thêm "— cần kiểm tra".

### Bằng chứng
Mỗi record lưu `snapshot` (HTML gốc) + entry trong `evidence` cho từng field parse được,
kèm `source_text` và độ tin cậy. `verify.py` đối chiếu value với chính snapshot.

## Chờ nội dung render (quan trọng)

Trang chi tiết là server-rendered nhưng script xen vào; chụp quá sớm cho ra trang ~45 KB
thiếu địa chỉ/diện tích, và lỗi này **âm thầm** làm record rơi về dữ liệu card.
`crawler.CONTENT_READY` khai báo selector đánh dấu nội dung đã sẵn sàng cho từng template:

| Platform | Selector chờ |
|---|---|
| `batdongsan_vn` (detail) | `h1.re__pr-title`, `div.re__pr-short-info-item` |
| `batdongsan_group` (detail) | `h1`, `div.property-content` |
| listing | `div.js__card-full-web` |

Nếu selector không xuất hiện sau 25 s, crawl ghi warning `content_marker_missing`
thay vì lặng lẽ lưu trang rỗng.

## Cloudflare

`batdongsan.com.vn` chặn headless. Quy trình:

1. Chạy với `--headed`; cửa sổ mở ra, human tick/chờ xác minh.
2. Session lưu vào `Temp/bds-profile` (gitignored) và dùng lại cho các lần sau.
3. Tool **không** bypass: không solver, không giả fingerprint.
4. Profile hết hạn → xoá `Temp/bds-profile` và chạy lại `--headed`.

## trạng thái record

| `extraction_status` | Nghĩa |
|---|---|
| `Đã parse HTML detail` | đủ dữ liệu từ trang chi tiết |
| `Đã parse HTML detail — cần kiểm tra` | có mâu thuẫn diện tích hoặc giá không chắc |
| `Chỉ có dữ liệu card listing — cần kiểm tra` | không vào được trang chi tiết, chỉ có card |
| `Không parse được nội dung` | thất bại hoàn toàn |

Queue item (`Báo cáo crawl`) có trạng thái riêng:
`success`, `warning`, `needs_review`, `failed`, `blocked`.

## Thêm website mới

1. Chạy `/discover-site` để lấy artifact + network evidence.
2. Nếu là platform mới: viết `adapters/<site>.py` với `parse_detail(html, url)`.
3. Thêm site vào `config/sites.json` (`platform`, `categories`, `detail_path_re`).
4. Nếu template cần chờ riêng: thêm entry vào `crawler.CONTENT_READY`.
5. Thêm test snapshot vào `regression.py`; chạy tới khi 0 fail.
6. Cập nhật `research/sites/<site-id>/template.md` + `integration.yaml`.
7. Không promote `active` khi chưa có user duyệt.

## Kiểm tra nhanh sau khi sửa

```powershell
.\.venv\Scripts\python.exe -m src.property_tool.regression   # phải 0 FAIL
.\.venv\Scripts\python.exe -m src.property_tool.verify research\jobs\<job>
```

`verify.py` bắt: giá tổng ≤ giá/m², giá < 100.000đ, diện tích < 5 m² hoặc > 200.000 m²,
số điện thoại sai dạng, ngày sai định dạng, confidence ngoài [0,1], địa chỉ còn dấu `·`,
địa chỉ/diện tích không xuất hiện trong snapshot.