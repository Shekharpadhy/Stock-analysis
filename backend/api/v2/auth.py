from fastapi import APIRouter
router = APIRouter()
@router.post('/auth/refresh')
def refresh(): return {'token': 'x'}

