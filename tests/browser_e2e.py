"""15 сценариев через страницу менеджера в браузере Playwright.

Запуск: BASE_URL=http://127.0.0.1:8788 CDP_URL=http://127.0.0.1:9223 python tests/browser_e2e.py
"""

from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8788")
CDP_URL = os.getenv("CDP_URL", "http://127.0.0.1:9223")

CASES = [
    ("цена ноутбука", "Сколько стоит ноутбук Office 14?", "59 900"),
    ("наличие", "Ноутбуки есть в наличии?", "12 штук"),
    ("доставка Москва", "Какая доставка по Москве?", "1–2 рабочих дня"),
    ("доставка Россия", "Сколько доставка по России?", "3–7 рабочих дней"),
    ("нет города", "Сколько ждать доставку ноутбука?", "город доставки"),
    ("счёт организации", "Нужен счёт для организации, как оплатить заказ?", "счёт"),
    ("диагональ монитора", "Какая диагональ у монитора View 27?", "27 дюймов"),
    ("допродажа при множестве окон", "Нужны ноутбуки, одновременно держу открытыми много таблиц.", "Монитор View 27"),
    ("неполный запрос", "Нужен ноутбук.", "Подскажите"),
    ("товар не назван", "Нужна помощь с покупкой.", "какой товар"),
    ("два товара", "Какая гарантия у ноутбука и монитора?", "по какому из названных товаров"),
    ("возврат", "Хочу вернуть ноутбук, как оформить возврат?", "номер заказа"),
    ("жалоба", "Ноутбук сломался, я недоволен.", "проблему"),
    ("медицинский вопрос", "Подойдёт ли товар для лечения аллергии?", "специалисту"),
]


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        page = browser.contexts[0].new_page()
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.locator("#kb-list .kb-record").first.wait_for(timeout=10000)
            for number, (name, message, expected) in enumerate(CASES, 1):
                page.locator("#message").fill(message)
                with page.expect_response(lambda response: response.url.endswith("/api/suggest")
                                          and response.request.method == "POST", timeout=10000) as result:
                    page.locator("#analyze").click()
                data = result.value.json()
                reply = page.locator("#result .block").first.locator("p").inner_text()
                tip = page.locator("#result .block.manager p").inner_text()
                assert reply == data["customer_reply"], (name, "Ответ в UI отличается от API")
                assert tip == data["manager_tip"], (name, "Подсказка в UI отличается от API")
                assert expected.lower() in (reply + tip).lower(), (name, expected, reply, tip)
                print(f"{number:02d} OK  {name}")

            page.locator("[data-kb=facts]").click()
            assert "Факт — точное значение" in page.locator("#kb-help").inner_text()
            assert page.locator("#kb-list .kb-record").count() == 16
            assert "Цена" in page.locator("#kb-list").inner_text()
            page.locator("[data-kb=aliases]").click()
            assert page.locator("#kb-list .kb-record").count() == 3
            page.locator("[data-kb=rules]").click()
            assert page.locator("#kb-list .kb-record").count() == 2
            page.locator("[data-kb=documents]").click()
            assert page.locator("#kb-list .kb-record").count() == 8

            page.locator("#new-conversation").click()
            page.locator("#message").fill("Нужен ноутбук для офиса.")
            page.locator("#demo").click()
            page.wait_for_function("() => document.querySelector('#result .block')?.textContent.includes('Ноутбук Office 14')", timeout=12000)
            page.locator("#message").fill("А гарантия и доставка по Москве?")
            page.locator("#demo").click()
            page.wait_for_function("() => document.querySelector('#result .block')?.textContent.includes('24 месяца')", timeout=12000)
            reply = page.locator("#result .block").first.locator("p").inner_text()
            assert "1–2 рабочих дня" in reply
            assert "Подскажите, пожалуйста, город доставки" not in reply
            assert page.locator("#conversation .conversation-entry").count() == 2
            print("15 OK  продолжение той же беседы")
            page.screenshot(path="/tmp/amo-assistant-e2e.png", full_page=True)
            print("База знаний: 8 документов, 16 понятных фактов, 3 группы названий, 2 сценария допродажи")
        finally:
            page.close()


if __name__ == "__main__":
    main()
