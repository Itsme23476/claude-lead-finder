#!/usr/bin/env python3
"""Local business leads from a niche and a city, using only Decodo's Web Data API.

  python3 find_leads.py roofers "Dallas, TX"
  python3 find_leads.py plumbers "Phoenix, AZ" "Tucson, AZ" --min-stars 4 --min-reviews 20 --email-only
  python3 find_leads.py                      runs the self-check, no API calls

How it keeps each lead cheap:
1. Google searches through the google_search template (with a few wording changes per city) return Google's map
   results: name, address, rating, reviews, and the business's own website link. No extra call to find websites.
   It stops searching a city once new searches stop finding new businesses.
2. Normal Google results are kept only if they're a real local business site (not a directory, and the homepage
   mentions the city). Star and review filters run before any website is read, so filtered leads cost nothing.
3. Each website is read once, as Markdown, on the standard proxy pool. Premium only if the site blocks it.
   The contact page is read only when the homepage has no email.
4. Junk addresses are dropped: image names, website-builder and placeholder emails, and made-up domains.
Every page read is saved to pages/ so Claude can score the leads later without new requests.
Needs DECODO_API_KEY=... in .env next to this file. Only public business pages are read.
"""
import argparse
import csv
import json
import re
import sys
import threading
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

HERE = Path(__file__).resolve().parent
API = "https://data.decodo.com/v1/"
# Wording changes per city. Google shows a different handful of map results for each one.
MODIFIERS = ("", "best", "top rated", "affordable", "local", "licensed", "family owned", "emergency", "commercial",
             "residential", "reviews", "near downtown", "north", "south", "east", "west", "24 hour", "trusted")
BATCH = 4  # searches per round; a city stops after a round that adds fewer than 2 new businesses
# Free-plan rates from help.decodo.com/docs/web-data-api-billing, per 1K requests. Used only to report the share of
# the free plan a run used. The free plan is a $5 monthly budget in the dashboard.
RATES = {"google": 1.00, "page": 0.50, "page_premium": 1.00}
FREE_BUDGET = 5.00
SKIP = ("yelp.", "yellowpages.", "facebook.", "instagram.", "linkedin.", "tripadvisor.", "google.", "bbb.org",
        "reddit.", "youtube.", "wikipedia.", "mapquest.", "angi.", "thumbtack.", "nextdoor.", "groupon.", "indeed.",
        "glassdoor.", "twitter.", "x.com", "tiktok.", "apple.com", "bing.", "foursquare.", "manta.", "expertise.com",
        "threebestrated.", "birdeye.", "healthgrades.", "zocdoc.", "opencare.", "webmd.", "vitals.", "ratemds.",
        "usnews.", "clutch.co", "upcity.", "houzz.", "homeadvisor.", "superpages.", "chamberofcommerce.", "procore.",
        "porch.", "buildzoom.", "bark.com", "networx.", "fixr.", "modernize.", "forbes.", "lawyers.com", "avvo.",
        "justia.", "findlaw.", "martindale.", "superlawyers.", "nerdwallet.", "realtor.com", "zillow.", "trulia.",
        "yahoo.", "bestpickreports.", "serviceagent.", "directory")
JUNK = ("example.", "sentry", "wixpress", "domain.com", "yourdomain", "youremail", "email.com", "godaddy", "squarespace",
        "wix.com", "schema.org", "@2x", "test@", "user@", "name@")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", re.I)
PHONE = re.compile(r"tel:\+?1?[\s.-]?(\d{3})[\s.-]?(\d{3})[\s.-]?(\d{4})|\(?\b(\d{3})\)?[\s.-](\d{3})[\s.-](\d{4})\b")
CONTACT = re.compile(r"contact|about|team|staff|location", re.I)
LINK = re.compile(r"\]\(([^)\s]+)")
FIELDS = ["name", "city", "source", "address", "rating", "reviews", "site", "emails", "phones"]
lock, calls = threading.Lock(), Counter()


def api_key():
    env = HERE / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("DECODO_API_KEY=") and line.split("=", 1)[1].strip():
            return line.split("=", 1)[1].strip()
    sys.exit("Add DECODO_API_KEY=your-key to .env first (copy .env.example).")


def call(body, kind):
    with lock:
        calls[kind] += 1
    req = urllib.request.Request(API + "scrape", json.dumps(body).encode(), {
        "Authorization": f"Bearer {api_key()}", "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def host_of(url):
    return urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")


def website(item):
    """The business's own website from a map result. Ad links (/aclk) are skipped, never followed."""
    for link in item.get("links", []):
        href = link.get("href", "")
        if link.get("title") == "Website" and href.startswith("http") and not any(s in host_of(href) for s in SKIP):
            return f"https://{host_of(href)}"
    return ""


def google(query, geo):
    for _ in range(2):  # one retry; failed requests aren't billed
        try:
            res = call({"target": "google_search", "query": query, "parse": True, "geo": geo}, "google")
            res = res["results"][0]["content"]["results"]["results"]
            return [i for p in res.get("local_pack", []) for i in p.get("items", [])], res.get("organic", [])
        except Exception as e:
            err = e
    print(f"  skipped search '{query}': {str(err)[:80]}")
    return [], []


def discover(niche, place, geo):
    """Map results first (local by definition), then normal results that look like business sites."""
    found = {}
    for start in range(0, len(MODIFIERS), BATCH):
        queries = [" ".join(w for w in (m, niche, "in", place) if w) for m in MODIFIERS[start:start + BATCH]]
        before = len(found)
        with ThreadPoolExecutor(BATCH) as ex:
            for local, organic in ex.map(lambda q: google(q, geo), queries):
                for b in local:
                    if site := website(b):
                        found.setdefault(host_of(site), {"name": b["title"], "source": "map", "address": b.get("address", ""),
                                                         "rating": b.get("rating", ""), "reviews": b.get("rating_count", ""), "site": site})
                for o in organic:
                    host = host_of(o.get("url") or o.get("link", ""))
                    if host and not any(s in host for s in SKIP):
                        found.setdefault(host, {"name": host, "source": "web", "address": "", "rating": "", "reviews": "", "site": f"https://{host}"})
        if len(found) - before < 2:  # ponytail: simple stop rule; tune BATCH or the 2 if a niche needs more searches
            break
    return list(found.values())


def page_text(url):
    for pool, kind in (("standard", "page"), ("premium", "page_premium")):
        try:
            res = call({"url": url, "markdown": True, "proxy_pool": pool}, kind).get("results", [{}])[0]
            content = res.get("content", "")
            if content and int(res.get("status_code") or 200) < 400:
                return content if isinstance(content, str) else json.dumps(content)
        except Exception:
            pass
    return ""


def emails(text, site):
    """Real-looking emails, the business's own domain first. Drops images, builders, placeholders and made-up domains."""
    host, keep = host_of(site), set()
    for e in EMAIL.findall(text):
        e = e.lower().strip(".")
        domain = e.split("@")[1]
        if (not e.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")) and not any(j in e for j in JUNK)
                and any(len(part) >= 3 for part in domain.split("."))):
            keep.add(e)
    return sorted(keep, key=lambda e: (not e.endswith(host), e))


def phones(text):
    return sorted({"".join(g for g in m if g) for m in PHONE.findall(text)})


def contact_link(markdown, site):
    """The site's own contact page (or about/team page) linked from its homepage."""
    found = [urljoin(site + "/", h) for h in LINK.findall(markdown)]
    found = [u for u in found if host_of(u) == host_of(site) and CONTACT.search(urlparse(u).path)]
    return sorted(found, key=lambda u: "contact" not in u.lower())[0] if found else ""


def enrich(lead, city):
    """Read the homepage (and the contact page if needed). Returns None for web results that aren't local."""
    home = page_text(lead["site"])
    if not home or (lead["source"] == "web" and city.lower() not in home.lower()):
        return None
    pages, found = [home], emails(home, lead["site"])
    if not found and (link := contact_link(home, lead["site"])):
        pages.append(page_text(link))
        found = emails(pages[-1], lead["site"])
    (HERE / "pages").mkdir(exist_ok=True)
    (HERE / "pages" / f"{host_of(lead['site'])}.md").write_text("\n\n---\n\n".join(pages), encoding="utf-8")
    return {**lead, "emails": "; ".join(found), "phones": "; ".join(phones("\n".join(pages)))}


def passes(lead, a):
    if a.min_stars or a.min_reviews:
        if lead["source"] != "map":
            return False  # only map results have stars and reviews
        if float(lead["rating"] or 0) < a.min_stars or int(lead["reviews"] or 0) < a.min_reviews:
            return False
    return True


def cost(counts):
    return sum(RATES[k] * n for k, n in counts.items()) / 1000


def main(a):
    t0 = time.time()
    out = HERE / f"leads-{re.sub(r'[^a-z0-9]+', '-', a.niche.lower()).strip('-')}.csv"
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig"))) if out.exists() else []
    seen, start = {host_of(r["site"]) for r in rows}, len(rows)
    if rows:
        print(f"{len(rows)} leads already in {out.name}, adding to it")
    for place in a.places:
        if a.max and len(rows) >= a.max:
            break
        city = place.split(",")[0].strip()
        found = [l for l in discover(a.niche, place, a.country) if host_of(l["site"]) not in seen and passes(l, a)]
        if a.max:
            found = found[:max(0, a.max - len(rows)) * 2]  # read a few spare, some get dropped
        with ThreadPoolExecutor(8) as ex:  # the free plan allows 10 requests a second
            new = [l for l in ex.map(lambda l: enrich(l, city), found) if l and (l["emails"] or not a.email_only)]
        new = new[:max(0, a.max - len(rows))] if a.max else new
        for l in new:
            l["city"] = place
            seen.add(host_of(l["site"]))
        rows += new
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"{place}: +{len(new)} leads ({sum(bool(l['emails']) for l in new)} with an email)   total {len(rows)}")
    n, mail, tel = len(rows), sum(bool(r["emails"]) for r in rows), sum(bool(r["phones"]) for r in rows)
    made, used, secs = n - start, sum(calls.values()), time.time() - t0
    print(f"\nDone in {secs // 60:.0f}m {secs % 60:.0f}s: {n} leads, {mail} with an email ({mail / max(n, 1):.0%}), {tel} with a phone")
    print(f"Requests this run: {calls['google']} Google searches, {calls['page']} page reads, "
          f"{calls['page_premium']} premium page reads = {used} for {made} new leads ({used / max(made, 1):.1f} per lead)")
    if made:
        print(f"This run used {cost(calls) / FREE_BUDGET:.1%} of the free plan. "
              f"At this rate the free plan covers about {FREE_BUDGET / (cost(calls) / made):,.0f} leads a month.")
    print(json.dumps({"leads": n, "new": made, "emails": mail, "phones": tel, "calls": dict(calls), "seconds": round(secs)}))
    print(out)


def check():
    item = {"title": "T Rock", "links": [{"href": "https://www.dallasroofer.com/?utm=gmb", "title": "Website"},
                                         {"href": "/maps/dir//x", "title": "Directions"}]}
    assert website(item) == "https://dallasroofer.com"
    assert website({"links": [{"href": "/aclk?sa=L&ai=x", "title": "Website"}]}) == ""
    assert website({"links": [{"href": "https://www.facebook.com/x", "title": "Website"}]}) == ""
    text = ("Email info@SmileDental.com or office@mail.smiledental.com, sales@gaf.com, z@x.ns, logo@2x.png, "
            "owner.smile@gmail.com. Call (512) 555-0134 or [call](tel:+15125353888)")
    assert emails(text, "https://smiledental.com") == ["info@smiledental.com", "office@mail.smiledental.com", "owner.smile@gmail.com", "sales@gaf.com"]
    assert phones(text) == ["5125353888", "5125550134"]
    md = "[Home](/) [About us](/about-us) [Book](https://other.com/contact) [Contact](https://www.smiledental.com/contact/)"
    assert contact_link(md, "https://smiledental.com") == "https://www.smiledental.com/contact/"
    a = argparse.Namespace(min_stars=4.0, min_reviews=20)
    assert passes({"source": "map", "rating": 4.5, "reviews": 30}, a)
    assert not passes({"source": "map", "rating": 4.5, "reviews": 10}, a)
    assert not passes({"source": "web", "rating": "", "reviews": ""}, a)
    assert passes({"source": "web", "rating": "", "reviews": ""}, argparse.Namespace(min_stars=0, min_reviews=0))
    assert abs(cost(Counter(google=8, page=20)) - (8 * 1 + 20 * 0.5) / 1000) < 1e-12
    print("self-check ok")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        check()
        sys.exit()
    p = argparse.ArgumentParser(description="Local business leads from Google's map results, with Decodo.")
    p.add_argument("niche", help='what kind of business, like "roofers"')
    p.add_argument("places", nargs="+", help='one or more cities, like "Dallas, TX"')
    p.add_argument("--country", default="United States", help="country Google searches from")
    p.add_argument("--min-stars", type=float, default=0, help="only map results with at least this rating")
    p.add_argument("--min-reviews", type=int, default=0, help="only map results with at least this many reviews")
    p.add_argument("--email-only", action="store_true", help="only keep leads with an email")
    p.add_argument("--max", type=int, default=0, help="stop after this many leads in total")
    main(p.parse_args())
