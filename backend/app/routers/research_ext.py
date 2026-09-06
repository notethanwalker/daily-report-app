from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FundamentalCache, ReportSnapshot, SymbolRegistry

router=APIRouter(prefix="/api/v1",tags=["research"])

@router.get("/security/{symbol}/catalysts")
def security_catalysts(symbol:str,db:Session=Depends(get_db)):
    s=symbol.upper();registry=db.get(SymbolRegistry,s);fund=db.get(FundamentalCache,s);terms={s}
    if registry:
        for value in [registry.name,registry.sector,registry.industry]:
            if value:terms.add(str(value).upper())
    report=db.query(ReportSnapshot).order_by(ReportSnapshot.created_at.desc()).first();matches=[]
    if report:
        payload=report.payload or {};articles=payload.get("top_market_news") or payload.get("market_news") or []
        for article in articles:
            text=f"{article.get('title','')} {article.get('why_it_matters','')} {' '.join(article.get('sectors') or [])} {' '.join(article.get('topics') or [])}".upper()
            hit=[t for t in terms if len(t)>=3 and t in text]
            if hit:
                matches.append({"title":article.get("title"),"url":article.get("url"),"domain":article.get("domain"),"published_at":article.get("published_at"),"why_it_matters":article.get("why_it_matters"),"matched_terms":hit[:4],"relationship":"possible catalyst; text/theme match does not prove causality"})
    upcoming=[]
    if fund and (fund.payload or {}).get("earnings_date"):
        upcoming.append({"kind":"earnings","date":fund.payload.get("earnings_date"),"title":f"{s} earnings","provider":fund.provider})
    return {"symbol":s,"news":matches[:12],"upcoming":upcoming,"source":"latest stored market-news report + cached fundamentals","provider_calls":0}
