"""Import Jobs API 路由（第一阶段预留，仅创建 ImportJob + BackgroundJob 的桩接口）"""

from fastapi import APIRouter

router = APIRouter()


# 第一阶段不实现完整智能导入链路
# 后续阶段将添加以下端点：
# - POST /api/banks/{bank_id}/import  (创建 ImportJob + BackgroundJob)
# - GET  /api/import-jobs/{import_job_id}
# - GET  /api/import-jobs/{import_job_id}/chunks
# - GET  /api/import-jobs/{import_job_id}/review-items
# - POST /api/import-review/{parsed_question_id}/accept
# - POST /api/import-review/{parsed_question_id}/skip
# - POST /api/import-chunks/{chunk_id}/reparse
