"""노션 데이터베이스 세 곳(서가·개념 연결망·사유의 변곡점)을 읽어
library/template.html 에 넣고 library/index.html 을 다시 만든다.
첫 화면(index.html)의 숫자와 갱신 날짜도 함께 바꾼다.

필요한 환경변수: NOTION_TOKEN (노션 통합의 Internal Integration Secret)
수집이 하나라도 실패하면 아무 파일도 바꾸지 않고 오류로 끝낸다
(오래되거나 반쯤 빈 페이지를 밀어 올리지 않기 위해서).
"""
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.notion.com/v1"
VERSION = "2025-09-03"
KST = dt.timezone(dt.timedelta(hours=9))

BOOKS_DS = "dfb385d4-963b-406e-835f-58b068d05df5"
CONCEPTS_DS = "a73b4803-6558-49e8-9817-aef1f8b9fe03"
TURNS_DS = "41ce61bb-cd98-8182-a454-000b9f53ec4f"


# ---------- 노션 API ----------
def query_all(token, ds_id, post=None):
    post = post or requests.post
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": VERSION, "Content-Type": "application/json"}
    rows, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        for attempt in range(4):
            r = post(f"{API}/data_sources/{ds_id}/query", headers=headers, data=json.dumps(body), timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            break
        if r.status_code != 200:
            raise RuntimeError(f"노션 조회 실패 {ds_id}: HTTP {r.status_code} {r.text[:300]}")
        j = r.json()
        rows += [p for p in j.get("results", []) if not p.get("in_trash") and not p.get("archived")]
        if not j.get("has_more"):
            return rows
        cursor = j.get("next_cursor")


# ---------- 속성 값 꺼내기 ----------
def page_url(page_id):
    return "https://app.notion.com/" + page_id.replace("-", "")


def text(prop):
    if not prop:
        return None
    t = prop.get("type")
    if t in ("title", "rich_text"):
        s = "".join(x.get("plain_text", "") for x in prop.get(t) or [])
        return s or None
    if t == "select":
        return (prop.get("select") or {}).get("name")
    if t == "status":
        return (prop.get("status") or {}).get("name")
    if t == "created_time":
        return prop.get("created_time")
    if t == "url":
        return prop.get("url")
    return None


def names(prop):
    if not prop:
        return []
    if prop.get("type") == "multi_select":
        return [x["name"] for x in prop.get("multi_select") or []]
    return []


def relation(prop):
    if not prop or prop.get("type") != "relation":
        return []
    return [page_url(x["id"]) for x in prop.get("relation") or []]


def date(prop, part="start"):
    if not prop or prop.get("type") != "date" or not prop.get("date"):
        return None
    return prop["date"].get(part)


def created(page, props, name):
    return text(props.get(name)) or page.get("created_time")


# ---------- 로비 페이지가 쓰는 모양으로 바꾸기 ----------
def books_rows(pages):
    out = []
    for p in pages:
        pr = p["properties"]
        out.append({
            "url": page_url(p["id"]),
            "이름": text(pr.get("이름")),
            "저자": text(pr.get("저자")),
            "상태": text(pr.get("상태")),
            "매체": text(pr.get("매체")),
            "분류": text(pr.get("분류")),
            "별점": text(pr.get("별점")),
            "한 줄 평": text(pr.get("한 줄 평")),
            "s": date(pr.get("읽은 기간")),
            "e": date(pr.get("읽은 기간"), "end"),
            "등록일": created(p, pr, "등록일"),
        })
    return out


def concept_rows(pages):
    out = []
    for p in pages:
        pr = p["properties"]
        out.append({
            "url": page_url(p["id"]),
            "개념": text(pr.get("개념")),
            "상태": text(pr.get("상태")),
            "한 줄 요지": text(pr.get("한 줄 요지")),
            "나의 사유": text(pr.get("나의 사유")),
            "출처 책": relation(pr.get("출처 책")),
            "주제": names(pr.get("주제")),
            "등록일": created(p, pr, "등록일"),
            "td": date(pr.get("사유한 날")),
        })
    return out


def turn_rows(pages):
    out = []
    for p in pages:
        pr = p["properties"]
        out.append({
            "url": page_url(p["id"]),
            "ct": p.get("created_time"),
            "변곡점": text(pr.get("변곡점")),
            "d": date(pr.get("날짜")),
            "개념 카드": relation(pr.get("개념 카드")),
            "그때의 문장": text(pr.get("그때의 문장")),
            "변화의 종류": text(pr.get("변화의 종류")),
            "계기": names(pr.get("계기")),
            "계기 출처": relation(pr.get("계기 출처")),
            "무엇이 움직였나": text(pr.get("무엇이 움직였나")),
        })
    return out


# ---------- 파일 쓰기 ----------
def js_array(rows):
    # </script> 같은 문자열이 데이터에 섞여도 스크립트가 끊기지 않도록
    return json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")


def render(books, concepts, turns, now):
    tpl = (ROOT / "library" / "template.html").read_text(encoding="utf-8")
    html = (tpl
            .replace("/*__BOOKS__*/[]", js_array(books))
            .replace("/*__CONCEPTS__*/[]", js_array(concepts))
            .replace("/*__TURNS__*/[]", js_array(turns))
            .replace('/*__NOW__*/"2026-11-19T12:00:00+09:00"', json.dumps(now.isoformat(timespec="seconds")))
            .replace("{{DOT_DATE}}", now.strftime("%Y.%m.%d"))
            .replace("{{KO_DATE}}", f"{now.year}년 {now.month}월 {now.day}일"))
    if "/*__BOOKS__*/" in html or "{{DOT_DATE}}" in html:
        raise RuntimeError("템플릿 자리표시자가 남았습니다.")
    return html


def update_hub(counts, now):
    path = ROOT / "index.html"
    h = path.read_text(encoding="utf-8")
    vals = dict(counts, date=now.strftime("%Y.%m.%d"))
    for k, v in vals.items():
        h, n = re.subn(rf"<!--n:{k}-->.*?<!--/n-->", f"<!--n:{k}-->{v}<!--/n-->", h)
        if n != 1:
            raise RuntimeError(f"첫 화면에서 '{k}' 자리를 찾지 못했습니다.")
    path.write_text(h, encoding="utf-8")


def main(post=None, now=None):
    token = os.environ.get("NOTION_TOKEN")
    if not token and post is None:
        sys.exit("NOTION_TOKEN 환경변수가 없습니다.")
    now = now or dt.datetime.now(KST)
    books = books_rows(query_all(token, BOOKS_DS, post))
    concepts = concept_rows(query_all(token, CONCEPTS_DS, post))
    turns = turn_rows(query_all(token, TURNS_DS, post))
    if not books:
        raise RuntimeError("서가가 비어 있습니다. 통합에 데이터베이스가 공유됐는지 확인하세요.")
    html = render(books, concepts, turns, now)
    (ROOT / "library" / "index.html").write_text(html, encoding="utf-8")
    update_hub({"books": len(books), "concepts": len(concepts), "turns": len(turns)}, now)
    print(f"서가 {len(books)} · 카드 {len(concepts)} · 변곡점 {len(turns)} · {now:%Y-%m-%d %H:%M} KST")


if __name__ == "__main__":
    main()
