from fastapi import APIRouter  # 경로 묶음(라우터)을 만드는 도구

router = APIRouter()  # 이 파일의 경로들을 담을 라우터


@router.get("/health")  # GET /api/v1/health 요청을 받는다 (앞부분 /api/v1은 main.py에서 붙인다)
def health() -> dict[str, str]:
    return {"status": "ok"}  # 서버가 살아 있으면 이 JSON을 200으로 돌려준다
