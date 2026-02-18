from backend.schemas.pagination import PaginationMeta, PaginatedResponse
from typing import List, TypeVar
T = TypeVar("T")

def paginate(items: List[T], page: int, page_size: int) -> PaginatedResponse:
    total = len(items)
    start = (page - 1) * page_size
    data = items[start: start + page_size]
    meta = PaginationMeta(
        page=page, page_size=page_size,
        total=total, total_pages=(total + page_size - 1) // page_size
    )
    return PaginatedResponse(data=data, meta=meta)
