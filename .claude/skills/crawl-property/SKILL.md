---
name: crawl-property
description: Chạy integration đã được duyệt để thu thập dữ liệu nhà đất.
---
# Crawl property
Ưu tiên integration active. Giữ URL nguồn, raw evidence và trạng thái từng bản ghi. Không loại bản ghi chỉ vì thiếu field.

## Chạy nền, chờ một lần
Crawl lớn mất 20–40 phút. Chạy một lệnh `run_in_background`, để cửa sổ tiến độ
tự mở (`src.property_tool/progress.py`), rồi chờ **một lần** đến khi harness báo
lệnh nền xong.

Không mở Monitor, không poll file tiến độ, không spawn agent chỉ để canh tiến
độ — mỗi vòng như vậy tốn token mà không thêm thông tin. Chỉ đọc kết quả khi có
thông báo hoàn tất. Chi tiết: skill `bat-dau-tim-du-lieu`.
