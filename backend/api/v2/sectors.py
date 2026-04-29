from fastapi import APIRouter
router = APIRouter()

@router.get('/sectors')
def list_sectors(cursor: str | None = None, limit: int = 50):
    return {'sectors': [], 'next_cursor': None}

