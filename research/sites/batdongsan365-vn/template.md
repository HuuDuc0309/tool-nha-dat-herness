# Site Integration — batdongsan365.vn

## Overview

- Site ID: `batdongsan365-vn`
- Domain: `batdongsan365.vn`
- Status: `tested` — chưa promote `active` (cần user duyệt + regression)
- Version: `1.0.0`
- Platform: `batdongsan_group` (chung markup listing với batdongsan.com.vn)

## Domain and Route Families

| Route family | Pattern | Ví dụ |
|---|---|---|
| Category listing | `/{category}/` | `/cho-thue-kho-nha-xuong/` |
| Pagination | `/{category}/?page={n}` | `/cho-thue-van-phong/?page=2` |
| Detail | `/{category}-{slug}[-bs{code}]/` | `/cho-thue-kho-nha-xuong-...-bs15426/` |
| Address suggest API | `/api/address-search/?q={q}` | chỉ autocomplete, không dùng crawl |

## Supported Flows

- ✅ Listing → card list (title, price, area, location, description, href)
- ✅ Pagination (`?page=n`, bắt đầu từ 1)
- ✅ Detail → h1, địa chỉ, attribute rows, posting meta, mô tả
- ❌ Search/filter submit (form tồn tại nhưng không cần cho crawl category-based)
- ❌ Phone reveal (sidebar bị mask)

## API / Feed Discovery

Không có JSON API cho listing/detail — trang render server-side HTML.
API duy nhất ghi nhận được: `/api/address-search/?q=` (autocomplete).

## Response Schema

HTML thuần, không có JSON-LD, không có embedded JSON blob, không có `window.*` data object.

## Field Mapping

Xem `integration.yaml` → `field_mapping`. Điểm mấu chốt:

| Field schema | Nguồn |
|---|---|
| `title` | `h1.h2` trên detail, fallback `re__card-title` |
| `address` | `p.b2` (dạng `Xã X, Huyện Y, Thành phố Z`) |
| `province`/`district`/`ward` | tách từ `address` theo tiền tố |
| `rent_amount` | `Mức giá` → VND, **chỉ khi là giá tổng** |
| `usable_area_m2` | `Diện tích` |
| `factory_area_m2` | regex trên mô tả: `diện tích (nhà )?xưởng <n> m` |
| `land_area_m2` | regex trên mô tả: `diện tích khuôn viên/đất/tổng <n> m` |
| `contact` | số điện thoại trong mô tả; sidebar bị mask |
| `listing_code` | `Mã tin` |

## Extraction Strategy

1. Crawl category listing, thu `div.js__card-full-web` (20 card/trang).
2. Thu URL detail từ card, đưa vào queue.
3. Mỗi detail: parse bằng `adapters/batdongsan_group.py:parse_detail()`.
4. Merge card + detail (detail ưu tiên), normalize giá/diện tích.
5. Ghi snapshot HTML làm evidence.

## Authentication

Không cần. Không có login wall cho nội dung công khai.

## Test Results

`2026-11-17` — crawl thật 5 category cho thuê, 3 trang listing/category, 200 detail cap:

- Parser detail trả về đúng: title, address (đủ ward/district/province), Mức giá, Diện tích, Pháp lý, Ngày đăng, Ngày hết hạn, Loại tin, Mã tin, mô tả.
- Giá theo m² (`65 nghìn` = `65 nghìn/m²`) được tách đúng: `rent_amount` để trống, `price_per_m2_vnd` = 65000, có warning.
- Số điện thoại mask được giữ nguyên dạng + `contact_masked=yes`, không bịa số.
- Diện tích `11.000m²` parse đúng thành 11000 (không bị cắt thành 11).

## Known Limitations

- Không có JSON-LD → phụ thuộc hoàn toàn vào markup; redesign sẽ làm hỏng parser.
- Số liên hệ bị mask (`******9528`); chỉ có trong mô tả nếu người đăng tự ghi.
- Đất/xưởng cho thuê báo giá theo m² → không có tổng giá thuê tháng.
- `deposit`, `frontage_m` site không cung cấp.
- Discovery heuristic báo `listing_detail: false` (false negative): nó tìm `chi-tiet`/`/p/` trong URL, còn URL thật là `/{category}-{slug}-bs{code}/`. Đã verify thủ công bằng cách fetch detail thật.
- 34 discovery "errors" là timeout click vào button tab bị ẩn ("Tìm mua"/"Tìm thuê"), không ảnh hưởng extraction.

## Special Notes

- Tồn kho nhóm cho thuê của site này **rất nhỏ** (kho/xưởng chỉ 3 tin tại 2026-11-17). Giá trị chính nằm ở batdongsan.com.vn.
- Dùng chung `re__card-*` markup với batdongsan.com.vn nên listing parser dùng chung; detail parser khác nhau.

## Fallback Scripts

```bash
# khám phá lại
.\.venv\Scripts\python.exe -m src.property_tool.discover https://batdongsan365.vn/ --out research/sites

# crawl (headless được)
.\.venv\Scripts\python.exe -m src.property_tool.crawler --sites batdongsan365-vn --out research/jobs/<job> --max-listing-pages 3 --max-details 200 --delay 1.5

# xuất Excel
.\.venv\Scripts\python.exe -m src.property_tool.exporter research/jobs/<job>
```

## Version History

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-11-17 | Integration đầu tiên: listing + detail parsing, evidence snapshots, xử lý giá theo m² |