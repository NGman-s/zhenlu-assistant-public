from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.errors import ApiError
from app.providers.demo_data import DemoCase
from app.schemas import DemoCaseListOut

router = APIRouter(prefix="/demo", tags=["演示数据"])


def _case_dict(case: DemoCase) -> dict:
    patient_lines = [line.text for line in case.dialogue if line.speaker == "患者"]
    preview = patient_lines[0] if patient_lines else case.dialogue[0].text
    return {
        "key": case.key,
        "title": case.title,
        "description": case.description,
        "audio_filename": case.audio_filename,
        "audio_url": f"/api/demo/cases/{case.key}/audio",
        "dialogue_preview": preview,
    }


@router.get("/cases", response_model=DemoCaseListOut)
def list_cases(request: Request) -> dict:
    catalog = request.app.state.demo_catalog
    return {"items": [_case_dict(case) for case in catalog.list()]}


@router.get("/cases/{case_key}/audio")
def demo_audio(case_key: str, request: Request) -> FileResponse:
    catalog = request.app.state.demo_catalog
    case = catalog.get(case_key)
    if case is None:
        raise ApiError(404, "demo_case_not_found", "示例病例不存在。")

    root = catalog.directory.resolve()
    path = (root / case.audio_filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ApiError(
            404, "demo_audio_missing", "示例音频文件缺失，请检查 sample-data 目录。"
        )
    media_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
    return FileResponse(
        path, media_type=media_type, headers={"Cache-Control": "no-store"}
    )
