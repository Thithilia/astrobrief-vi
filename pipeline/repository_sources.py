"""Discover DOI-linked institutional publisher copies; identity is checked later."""
from pathlib import Path

from bs4 import BeautifulSoup

from .fulltext import FetchCache, FullTextUnavailable
from .store import normalize_doi

FEED="https://feeds.library.caltech.edu/groups/Astronomy-Department/article.html"


def parse_leads(raw: bytes) -> dict[str,str]:
    result={}
    for item in BeautifulSoup(raw,"html.parser").find_all("li"):
        links=item.find_all("a",href=True)
        doi=next((normalize_doi(a["href"]) for a in links if str(a["href"]).startswith(("https://doi.org/10.","http://doi.org/10."))),"")
        record=next((a["href"] for a in links if str(a["href"]).startswith("https://authors.library.caltech.edu/records/")),None)
        if doi and record: result[doi]=record
    return result


def discover_leads(store,root: Path):
    try:
        response=FetchCache(root/".local/cache").get(FEED,ttl=3600)
        leads=parse_leads(response["body"])
    except FullTextUnavailable as exc:
        return {"new_leads":0,"status":exc.reason}
    count=0
    for doi,url in leads.items():
        p=store.get_paper(doi)
        if not p or p.get("repository_url")==url: continue
        store.upsert_papers([{"doi":doi,"journal":p["journal"],"repository_url":url}])
        store.conn.execute("UPDATE editorial_items SET state='pending',retry_at=NULL WHERE doi=? AND state IN ('waiting_source','pending')",(doi,))
        store.conn.commit();count+=1
    return {"new_leads":count,"status":"ok"}
