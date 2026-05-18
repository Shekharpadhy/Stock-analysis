from fastapi import APIRouter
router = APIRouter()
@router.get('/export.csv')
def export(): return 'csv'

