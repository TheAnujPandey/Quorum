from fastapi import APIRouter

from api.core.config import settings
from api.models.schemas import ConfigResponse

router = APIRouter(tags=["config"])


@router.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    return ConfigResponse(
        default_model=settings.openai_model,
        openai_key_configured=bool(settings.openai_api_key and settings.openai_api_key != "sk-your-key-here"),
    )
