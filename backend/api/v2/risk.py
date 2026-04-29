from fastapi import APIRouter
router = APIRouter()

@router.get('/risk/{ticker}')
def risk(ticker: str):
    return {'ticker': ticker, 'bands': {}}

