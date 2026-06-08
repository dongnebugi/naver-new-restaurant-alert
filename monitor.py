import os
import re
import json
import hashlib
import urllib.parse
from pathlib import Path

import requests


KNOWN_FILE = Path("known_places.json")

NAVER_CLIENT_ID = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]

KAKAO_REST_API_KEY = os.environ["KAKAO_REST_API_KEY"]
KAKAO_REFRESH_TOKEN = os.environ["KAKAO_REFRESH_TOKEN"]
KAKAO_CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET", "")

SEARCH_QUERIES = [
    q.strip()
    for q in os.environ.get(
        "SEARCH_QUERIES",
        "대구 신상 맛집,대구 새로오픈 식당,대구 신규 식당,대구 오픈 맛집,동성로 신상 맛집,범어동 신상 맛집,수성구 신상 맛집,달서구 신상 맛집,칠곡 신상 맛집,경산 신상 맛집,구미 신상 맛집",
    ).split(",")
    if q.strip()
]


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return text.replace("&amp;", "&").strip()


def make_place_id(title: str, road_address: str, address: str) -> str:
    base = f"{clean_text(title)}|{road_address or address}".lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def load_known_places():
    if not KNOWN_FILE.exists():
        return []

    try:
        return json.loads(KNOWN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_known_places(places):
    KNOWN_FILE.write_text(
        json.dumps(places, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def naver_search(query: str):
    url = "https://openapi.naver.com/v1/search/local.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": query,
        "display": 5,
        "start": 1,
    }

    response = requests.get(url, headers=headers, params=params, timeout=15)
    response.raise_for_status()

    items = response.json().get("items", [])
    results = []

    for item in items:
        title = clean_text(item.get("title", ""))
        category = clean_text(item.get("category", ""))
        address = clean_text(item.get("address", ""))
        road_address = clean_text(item.get("roadAddress", ""))
        link = item.get("link") or ""

        place_id = make_place_id(title, road_address, address)

        search_url = "https://map.naver.com/v5/search/" + urllib.parse.quote(
            f"{title} {road_address or address}"
        )

        results.append(
            {
                "id": place_id,
                "title": title,
                "category": category,
                "address": address,
                "roadAddress": road_address,
                "link": link or search_url,
                "foundQuery": query,
            }
        )

    return results


def get_kakao_access_token():
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": KAKAO_REFRESH_TOKEN,
    }

    if KAKAO_CLIENT_SECRET:
        data["client_secret"] = KAKAO_CLIENT_SECRET

    response = requests.post(url, data=data, timeout=15)
    response.raise_for_status()

    token_data = response.json()
    return token_data["access_token"]


def send_kakao_message(access_token: str, text: str, link_url: str):
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

    text = text[:190]

    template_object = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": link_url,
            "mobile_web_url": link_url,
        },
        "button_title": "확인하기",
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    data = {
        "template_object": json.dumps(template_object, ensure_ascii=False),
    }

    response = requests.post(url, headers=headers, data=data, timeout=15)
    response.raise_for_status()
    print("카카오톡 발송 완료:", text.replace("\n", " / "))


def main():
    known_places = load_known_places()
    known_ids = {place["id"] for place in known_places if "id" in place}

    all_found = []
    seen_ids = set()

    for query in SEARCH_QUERIES:
        print(f"검색 중: {query}")
        try:
            places = naver_search(query)
        except Exception as e:
            print(f"네이버 검색 실패: {query} / {e}")
            continue

        for place in places:
            if place["id"] not in seen_ids:
                seen_ids.add(place["id"])
                all_found.append(place)

    new_places = [place for place in all_found if place["id"] not in known_ids]

    merged = {place["id"]: place for place in known_places if "id" in place}
    for place in all_found:
        merged[place["id"]] = place

    save_known_places(list(merged.values()))

    access_token = get_kakao_access_token()

    if not known_ids:
        text = (
            "신규식당알림 세팅 완료\n"
            f"기준 목록 {len(all_found)}개 저장\n"
            "다음 실행부터 신규 발견 시 알림"
        )
        send_kakao_message(access_token, text, "https://map.naver.com/")
        return

    if not new_places:
        print("신규 식당 없음")
        return

    send_count = len(new_places)

    for place in new_places[:send_count]:
        address = place.get("roadAddress") or place.get("address") or ""
        text = (
            "신규 식당 발견\n"
            f"{place['title']}\n"
            f"{address[:60]}\n"
            f"검색어: {place['foundQuery']}"
        )
        send_kakao_message(access_token, text, place["link"])

    if len(new_places) > send_count:
        text = f"신규 식당이 총 {len(new_places)}개 발견됐어요. 먼저 {send_count}개만 알림으로 보냈어요."
        send_kakao_message(access_token, text, "https://map.naver.com/")


if __name__ == "__main__":
    main()
