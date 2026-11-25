from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.core.security import get_principal
from app.db.clinic_addresses import address_query, find_addresses
from app.db.clinic_catalog import search_clinics, within_pilot
from app.schemas.clinics import (
    ClinicSearch,
    ClinicSearchResponse,
    GeocodeRequest,
    GeocodeResponse,
)

router = APIRouter(prefix="/api/v1/clinics", tags=["clinics"])


@router.post("/geocode", response_model=GeocodeResponse, dependencies=[Depends(get_principal)])
async def geocode(body: GeocodeRequest, request: Request):
    try:
        query = address_query(body.address)
    except ValueError:
        raise HTTPException(status_code=422, detail="clinic_outside_pilot") from None
    factory = request.app.state.clinic_db
    if factory is None:
        raise HTTPException(status_code=503, detail="clinic_addresses_unavailable")
    try:
        async with factory() as db:
            candidates = await find_addresses(db, *query)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="clinic_addresses_unavailable") from None
    return GeocodeResponse(candidates=candidates)


@router.post("/search", response_model=ClinicSearchResponse, dependencies=[Depends(get_principal)])
async def search(body: ClinicSearch, request: Request):
    if not within_pilot(body.lat, body.lon):
        raise HTTPException(status_code=422, detail="clinic_outside_pilot")
    factory = request.app.state.clinic_db
    if factory is None:
        raise HTTPException(status_code=503, detail="clinic_catalog_unavailable")
    try:
        async with factory() as db:
            return await search_clinics(db, body, request.app.state.settings.demo_mode)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="clinic_catalog_unavailable") from None
