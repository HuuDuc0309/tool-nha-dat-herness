---
name: bat-dau-tim-du-lieu
description: Discovery-first thu thập dữ liệu nhà đất từ nhiều website và xuất Excel.
---
# Bắt đầu tìm dữ liệu

## Bắt buộc: discovery gate trước crawl

Khi user gửi URL:
1. Hỏi các field muốn xuất; hiển thị field mặc định từ `config/property-fields.json`.
2. Không gọi curl/HTTP extractor như output cuối ngay lập tức.
3. Chạy discovery-first: `python -m src.property_tool.orchestrator <urls> --max-pages 20`.
4. Với site chưa có artifact: explorer mở browser, duyệt internal routes, forms, search/filter/pagination/detail, ghi request/response, screenshot và snapshot.
5. Với site đã có artifact: revalidate/replay full discovery; không tin artifact cũ chỉ vì file tồn tại.
6. Chỉ sau khi discovery report, completeness checks và artifact candidate được ghi mới chạy extraction/crawl.
7. Nếu artifact incomplete hoặc site bị CAPTCHA/Cloudflare, tự chuyển sang headed browser để human xử lý; hiển thị action rõ ràng, chờ tối đa 300 giây, sau đó verify artifact lại. Nếu vẫn lỗi, ghi trạng thái blocked/needs_review và báo action tiếp theo cụ thể; không giả vờ crawl thành công.
8. Parse → verify → export Excel, giữ toàn bộ record và URL nguồn.

## Artifact

Lưu tại `research/sites/<site-id>/` gồm `manifest.json`, `discovery.json`, `template.md`, `discovery/`, routes, interactions, API candidates, response catalog, HTML và screenshot. Artifact là website knowledge base, không phải một curl response.

## Quy tắc

- Hãy giải  CAPTCHA/Cloudflare trước (nếu gặp) rồi mới đi đến bước tiếp. 
- Không lưu secret vào report/Excel.
- Không pre-filter dữ liệu trong MVP.
- Field thiếu ghi `Chưa xác định`, giữ record và evidence.
- Site không complete không được promote active.
