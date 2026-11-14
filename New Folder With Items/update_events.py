#!/usr/bin/env python3
"""Best-effort public search discovery of Facebook events, no credentials or paid API.
Only publish records with a defensible date found in the search result. No fake metadata.
"""
import datetime as dt, email.utils, hashlib, html, json, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'data'/'facebook-events.json'
SEARCHES=['site:facebook.com/events/ Tallinn 2026 November', 'site:facebook.com/events/ Tallinn 2026 December', 'site:facebook.com/events/ Tallinn upcoming event']
MONTHS={'jaanuar':1,'veebruar':2,'märts':3,'aprill':4,'mai':5,'juuni':6,'juuli':7,'august':8,'september':9,'oktoober':10,'november':11,'detsember':12,'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,'july':7,'august':8,'september':9,'october':10,'november':11,'december':12}

def date_from(text):
    # Date extraction from the actual result, not the crawler timestamp.
    m=re.search(r'(?<!\d)(20\d\d)[-./](0?[1-9]|1[0-2])[-./]([0-2]?\d|3[01])(?!\d)',text)
    if m:
        try:return dt.date(*map(int,m.groups())).isoformat()
        except ValueError:pass
    m=re.search(r'(?<!\d)([0-2]?\d|3[01])[. /-]+(0?[1-9]|1[0-2])[. /-]+(20\d\d)(?!\d)',text)
    if m:
        try:return dt.date(int(m[3]),int(m[2]),int(m[1])).isoformat()
        except ValueError:pass
    m=re.search(r'(?<!\d)([0-2]?\d|3[01])\.?\s+('+ '|'.join(MONTHS) +r')(?:\s+(20\d\d))',text,re.I)
    if m:
        try:return dt.date(int(m[3]),MONTHS[m[2].lower()],int(m[1])).isoformat()
        except ValueError:pass
    return None

def search(query):
    url='https://www.bing.com/search?format=rss&q='+urllib.parse.quote(query)
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 NIGHTLY public events discovery'})
    with urllib.request.urlopen(req,timeout=18) as response: raw=response.read(2_000_000)
    root=ET.fromstring(raw)
    for item in root.findall('.//item'):
        yield {tag:html.unescape(item.findtext(tag,'')).strip() for tag in ('title','link','description')}

def main():
    old=[]
    if OUT.exists():
        try:old=json.loads(OUT.read_text()).get('events',[])
        except (ValueError,TypeError):pass
    # Retain still-upcoming previously found events, even if search is temporarily unavailable.
    today=dt.date.today().isoformat(); found={e['url']:e for e in old if isinstance(e,dict) and e.get('date','')>=today and e.get('url','').startswith('https://www.facebook.com/events/')}
    errors=[]
    for query in SEARCHES:
        try:
            for r in search(query):
                link=r['link'].split('?')[0].rstrip('/')
                match=re.search(r'(?:https?://)?(?:www\.|m\.)?facebook\.com/events/(\d+)',link,re.I)
                if not match:continue
                url='https://www.facebook.com/events/'+match.group(1)+'/'
                combined=r['title']+' '+r['description']
                # Must explicitly mention Tallinn and a real future event date.
                if 'tallinn' not in combined.lower():continue
                day=date_from(combined)
                if not day or day<today:continue
                title=re.sub(r'\s*[-|·]\s*Facebook.*$','',r['title'],flags=re.I).strip()
                if not title:continue
                found[url]={'id':int(hashlib.sha256(url.encode()).hexdigest()[:12],16),'date':day,'time':'','title':title[:160], 'venue':'Vaata Facebookist','address':'','district':'Kesklinn','category':'Muu','price':'Vaata Facebookist','url':url,'seller':'Facebook','age':'Kontrolli korraldajalt','directTicket':False,'soldOut':False,'unverified':True}
        except Exception as exc:errors.append(type(exc).__name__+': '+str(exc)[:160])
    events=sorted(found.values(),key=lambda e:(e['date'],e['title']))[:150]
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({'updated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'events':events,'note':'Avaliku otsingu tulemused; andmed vajavad korraldaja juures kontrollimist. Mitte Facebooki ametlik API.'},ensure_ascii=False,indent=2)+'\n')
    print('Found',len(events),'events. Search errors:',errors)

if __name__=='__main__':main()
