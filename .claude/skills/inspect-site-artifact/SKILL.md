---
name: inspect-site-artifact
description: Kiểm tra read-only completeness và các lỗi của artifact website.
---
# Inspect site artifact

Chạy:
```powershell
.\.venv\Scripts\python.exe -m src.property_tool.artifact_verify research\sites\<site-id>
```
Không đánh dấu complete nếu thiếu required checks, discovery errors hoặc phase report lỗi.
