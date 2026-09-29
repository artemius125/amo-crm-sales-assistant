"""Сценарии страницы с включённым AITUNNEL; запросы расходуют небольшой баланс."""

from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8787")
CDP_URL = os.getenv("CDP_URL", "http://127.0.0.1:9223")


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        page = browser.contexts[0].new_page()
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.locator("#health").filter(has_text="AITUNNEL включён").wait_for(timeout=10000)
            cases = [
                ("неявная потребность", "Нужен ноутбук для работы с таблицами, постоянно переключаюсь между окнами. Что посоветуете?", "offer"),
                ("возврат", "Хочу вернуть ноутбук, он не работает. Как оформить?", "none"),
                ("нет товара", "Ищу что-то для работы, но пока не знаю, что выбрать.", "clarify"),
            ]
            for number, (name, message, expected_stage) in enumerate(cases, 1):
                page.locator("#message").fill(message)
                with page.expect_response(lambda response: response.url.endswith("/api/suggest")
                                          and response.request.method == "POST", timeout=30000) as result:
                    page.locator("#analyze").click()
                data = result.value.json()
                assert data["recommendation_stage"] == expected_stage, (name, data)
                assert data["customer_reply"] == page.locator("#result .block").first.locator("p").inner_text()
                assert data["manager_tip"] == page.locator("#result .block.manager p").inner_text()
                if name == "неявная потребность":
                    assert "Монитор View 27" in data["manager_tip"]
                    assert "переключ" in data["analysis"]["need_quote"].lower(), data["analysis"]
                    assert data["retrieval_hits"]
                print(f"AI {number} OK  {name} · {data['mode']}")
            page.screenshot(path="/tmp/amo-assistant-ai-e2e.png", full_page=True)
        finally:
            page.close()


if __name__ == "__main__":
    main()
