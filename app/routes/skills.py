from fastapi import APIRouter
from typing import List, Dict
from app.utils.skills_manager import list_skills

router = APIRouter()


@router.get("/api/skills", response_model=List[Dict])
async def get_skills():
    """Return all enabled skills for the frontend settings panel."""
    return list_skills()
