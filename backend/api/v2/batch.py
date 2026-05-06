from fastapi import APIRouter
router = APIRouter()
@router.post('/batch/score')
def score(tickers: list[str]):
    return {'jobs': []}

