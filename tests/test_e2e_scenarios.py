"""Пятнадцать пользовательских сценариев через HTTP API приложения."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from sales_assistant.api import create_app
from sales_assistant.config import PROJECT_ROOT, Settings


class EndToEndScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        kb = root / "knowledge.sqlite3"
        with sqlite3.connect(kb) as db:
            db.executescript((PROJECT_ROOT / "knowledge" / "demo.sql").read_text(encoding="utf-8"))
        settings = replace(Settings.from_env(), knowledge_db_path=kb,
                           database_path=root / "messages.sqlite3",
                           llm_api_key="", publish_notes=False,
                           webhook_secret="scenario-secret")
        cls.client = TestClient(create_app(settings))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.temp.cleanup()

    def suggest(self, message: str) -> dict:
        response = self.client.post("/api/suggest", json={"message": message})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_01_price(self) -> None:
        result = self.suggest("Сколько стоит ноутбук Office 14?")
        self.assertIn("59 900", result["customer_reply"])
        self.assertEqual(result["selected_product"], "laptop")

    def test_02_stock(self) -> None:
        result = self.suggest("Ноутбуки есть в наличии?")
        self.assertIn("12 штук", result["customer_reply"])

    def test_03_moscow_delivery(self) -> None:
        result = self.suggest("Какая доставка по Москве?")
        self.assertIn("1–2 рабочих дня", result["customer_reply"])
        self.assertNotIn("3–7", result["customer_reply"])

    def test_04_russia_delivery(self) -> None:
        result = self.suggest("Сколько доставка по России?")
        self.assertIn("3–7 рабочих дней", result["customer_reply"])

    def test_05_delivery_without_city(self) -> None:
        result = self.suggest("Сколько ждать доставку ноутбука?")
        self.assertIn("город доставки", result["customer_reply"])

    def test_06_corporate_invoice(self) -> None:
        result = self.suggest("Нужен счёт для организации, как оплатить заказ?")
        self.assertIn("счёт", result["customer_reply"])

    def test_07_monitor_size(self) -> None:
        result = self.suggest("Какая диагональ у монитора View 27?")
        self.assertIn("27 дюймов", result["customer_reply"])

    def test_08_office_upsell(self) -> None:
        result = self.suggest("Нужны ноутбуки, одновременно держу открытыми много таблиц.")
        self.assertEqual(result["recommendation_stage"], "offer")
        self.assertIn("Монитор View 27", result["manager_tip"])

    def test_09_vague_product(self) -> None:
        result = self.suggest("Нужен ноутбук.")
        self.assertEqual(result["recommendation_stage"], "clarify")
        self.assertIn("Подскажите", result["customer_reply"])

    def test_10_unknown_product(self) -> None:
        result = self.suggest("Нужна помощь с покупкой.")
        self.assertIsNone(result["selected_product"])
        self.assertIn("какой товар", result["customer_reply"])

    def test_11_multiple_products(self) -> None:
        result = self.suggest("Какая гарантия у ноутбука и монитора?")
        self.assertIsNone(result["selected_product"])
        self.assertIn("по какому из названных товаров", result["customer_reply"])

    def test_12_return(self) -> None:
        result = self.suggest("Хочу вернуть ноутбук, как оформить возврат?")
        self.assertEqual(result["recommendation_stage"], "none")
        self.assertIn("номер заказа", result["customer_reply"])

    def test_13_complaint(self) -> None:
        result = self.suggest("Ноутбук сломался, я недоволен.")
        self.assertEqual(result["recommendation_stage"], "none")
        self.assertIn("проблему", result["customer_reply"])

    def test_14_medical(self) -> None:
        result = self.suggest("Подойдёт ли товар для лечения аллергии?")
        self.assertEqual(result["recommendation_stage"], "none")
        self.assertIn("специалисту", result["customer_reply"])

    def test_15_followup_in_same_conversation(self) -> None:
        conversation = "scenario-followup"
        first = self.client.post("/api/demo-message", json={
            "message": "Нужен ноутбук для офиса.", "conversation_id": conversation})
        self.assertEqual(first.status_code, 200)
        second = self.client.post("/api/demo-message", json={
            "message": "А гарантия и доставка по Москве?", "conversation_id": conversation})
        self.assertEqual(second.status_code, 200)
        item = self.client.get("/api/inbox/" + second.json()["id"]).json()
        result = item["suggestion"]
        self.assertEqual(item["status"], "ready")
        self.assertEqual(result["selected_product"], "laptop")
        self.assertIn("24 месяца", result["customer_reply"])
        self.assertIn("1–2 рабочих дня", result["customer_reply"])
        self.assertNotIn("Подскажите, пожалуйста, город доставки", result["customer_reply"])


if __name__ == "__main__":
    unittest.main()
