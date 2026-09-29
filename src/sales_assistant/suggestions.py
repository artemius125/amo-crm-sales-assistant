"""Два проверяемых блока без LLM: только факты и правила из SQLite."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import httpx

from .ai import Insight, analyze
from .config import Settings
from .retrieval import Document, Fact, KnowledgeIndex, tokens

COMPLAINT = {"жалоб", "слома", "неисправ", "проблем", "брак", "недовол", "претенз"}
RETURN = {"возврат", "вернут", "отмен", "отказ"}
HEALTH = {"лечен", "болезн", "симптом", "диагноз", "беремен", "врач", "аллерг"}
FACETS = {
    "price": {"цен", "сто", "стоим", "выйд"},
    "stock": {"налич", "остаток", "прода"},
    "warranty": {"гарант"},
    "ports": {"порт", "hdmi", "usb", "подключ"},
    "size": {"диагонал", "размер", "дюйм"},
    "payment": {"оплат", "счет", "счету", "реквизит"},
    "corporate": {"организац", "юрлиц", "корпоратив", "коммерческ"},
}
OPEN_ADVICE = {"совет", "порекоменду", "подбер", "подход", "вариант"}
REGIONAL_CITIES = {"казан", "санкт", "петербург", "новосибир", "екатеринбург",
                   "нижн", "краснодар", "самар", "ростов", "уф", "перм",
                   "воронеж", "омск", "тюмен", "соч"}


@dataclass(frozen=True)
class Evidence:
    id: str
    title: str
    source: str
    reviewed_at: str
    bm25: float


@dataclass(frozen=True)
class Suggestion:
    customer_reply: str
    manager_tip: str
    evidence: list[Evidence]
    manager_evidence: list[Evidence]
    retrieval_hits: list[Evidence]
    mode: str
    needs_review: bool
    notice: str
    selected_product: str | None
    recommendation_stage: str
    analysis: dict[str, object] | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _intent(stems: set[str]) -> str:
    for name, markers in (("complaint", COMPLAINT), ("return", RETURN), ("health", HEALTH)):
        if _has(stems, markers):
            return name
    return "sales"


def _has(stems: set[str], markers: set[str]) -> bool:
    return any(stem.startswith(marker) for stem in stems for marker in markers)


def _requested(stems: set[str]) -> set[str]:
    categories = {category for category, markers in FACETS.items() if _has(stems, markers)}
    if _has(stems, {"достав", "привез", "вез", "едет"}):
        if _has(stems, {"москв"}):
            categories.add("delivery_moscow")
        elif _has(stems, {"росс", "регион"} | REGIONAL_CITIES):
            categories.add("delivery_russia")
        else:
            categories.add("delivery_unknown")
    # «Есть что-нибудь подходящее?» — подбор, а не вопрос об остатках.
    if _has(stems, {"ест", "есть"}) and not _has(stems, OPEN_ADVICE):
        categories.add("stock")
    return categories


def _render_fact(fact: Fact, product_name: str | None) -> str:
    name = f"товара «{product_name}»" if product_name else "товара"
    return {
        "price": f"Цена {name} по базе знаний — {fact.value}.",
        "stock": f"По данным базы, остаток {name} — {fact.value}.",
        "warranty": f"Гарантия для {name} — {fact.value}.",
        "ports": f"Разъёмы {name}: {fact.value}.",
        "size": f"Диагональ {name} — {fact.value}.",
        "delivery_moscow": f"Доставка по Москве: {fact.value}.",
        "delivery_russia": f"Доставка по России: {fact.value}.",
        "payment": f"По оплате: {fact.value}.",
        "corporate": f"Для корпоративного предложения уточним {fact.value}.",
        "return": f"Для оформления обращения {fact.value}.",
    }[fact.category]


class SuggestionEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.index = KnowledgeIndex(settings.knowledge_db_path)

    def suggest(self, message: str, previous_messages: list[str] | None = None) -> Suggestion:
        message = re.sub(r"\s+", " ", message).strip()[:5000]
        if not message:
            raise ValueError("Пустое обращение")
        stems = set(tokens(message))
        intent = _intent(stems)
        mentioned = self.index.mentioned_products(message)
        product = next(iter(mentioned)) if len(mentioned) == 1 else None
        inferred_screen = (_has(stems, {"экра"}) and _has(stems, {"втор", "дополнитель"})
                           and mentioned == {"laptop"} and "monitor" in self.index.documents)
        if inferred_screen:
            product = "monitor"
        context_used = False
        history = (previous_messages or [])[:5]
        if not mentioned:
            for previous in history:
                candidates = self.index.mentioned_products(previous)
                if len(candidates) == 1:
                    product = next(iter(candidates))
                    context_used = True
                    break
                if len(candidates) > 1:
                    break
        product_doc = (next((doc for doc in self.index.documents.values()
                             if doc.product_id == product), None) if product else None)
        query = message + (" " + product_doc.title if context_used and product_doc else "")
        requested_now = _requested(stems)
        if "delivery_russia" in requested_now:
            query += " доставка по России"
        elif "delivery_moscow" in requested_now:
            query += " доставка по Москве"
        first_hits = self.index.search(query, limit=8)
        insight: Insight | None = None
        model_product = inferred_screen
        ai_notice = ""
        if self.settings.llm_api_key:
            try:
                insight = analyze(self.settings, self.index, message, history, first_hits)
                if intent == "sales" and insight.intent != "sales":
                    intent = insight.intent
                if not mentioned and not context_used and insight.product_id and insight.need_quote:
                    product = insight.product_id
                    model_product = True
                    product_doc = next((doc for doc in self.index.documents.values()
                                        if doc.product_id == product), None)
                query += " " + insight.search_query
                if product_doc:
                    query += " " + product_doc.title
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 402:
                    ai_notice = "На балансе AITUNNEL недостаточно средств; показан ответ по локальным правилам."
                elif isinstance(exc, httpx.TimeoutException):
                    ai_notice = "AITUNNEL отвечает слишком долго; показан ответ по локальным правилам."
                else:
                    ai_notice = "AI не смог надёжно разобрать обращение; показан ответ по локальным правилам."
        hits = self.index.search(query, limit=8)
        if product:
            hits = [hit for hit in hits if hit.document.kind != "product"
                    or hit.document.product_id == product]
        if _has(stems, {"москв"}):
            hits = [hit for hit in hits if hit.document.id != "delivery-russia"]
        hit_scores = {hit.document.id: hit.bm25 for hit in hits}
        cited: dict[str, Document] = {}
        notice = "Товар взят из предыдущей реплики этой беседы; проверьте контекст." if context_used else ""
        if model_product:
            notice = "Товар определён моделью как гипотеза; подтвердите его у клиента."
        if ai_notice:
            notice = (notice + " " + ai_notice).strip()
        manager_source: Document | None = None
        stage = "none"

        if intent == "health":
            answer = ("Здравствуйте! По вопросам лечения, противопоказаний и выбора товара по симптомам "
                      "обратитесь, пожалуйста, к специалисту. Могу уточнить состав и условия заказа "
                      "конкретного товара.")
            tip = "Не предлагайте дополнения по симптомам. Уточните товар и передайте медицинский вопрос специалисту."
        elif intent in {"complaint", "return"}:
            facts = self.index.facts({"return"}, None)
            for fact in facts:
                cited[fact.document_id] = self.index.documents[fact.document_id]
            answer = ("Здравствуйте! Сожалеем, что возникла такая ситуация. "
                      "Напишите, пожалуйста, номер заказа и кратко опишите проблему. "
                      "Мы проверим данные заказа и сообщим дальнейшие шаги.")
            tip = "Допродажа неуместна. Сначала проверьте заказ и решите вопрос клиента."
        else:
            categories = set(requested_now)
            needs_city = False
            if "delivery_unknown" in categories:
                categories.remove("delivery_unknown")
                prior_stems = set(tokens(" ".join(history))) if context_used else set()
                if _has(prior_stems, {"москв"}):
                    categories.add("delivery_moscow")
                elif _has(prior_stems, {"росс", "регион"} | REGIONAL_CITIES):
                    categories.add("delivery_russia")
                else:
                    needs_city = True
                    notice = (notice + " Для точного срока доставки нужен город клиента.").strip()
            facts = self.index.facts(categories, product)
            matched_ids = {hit.document.id for hit in hits}
            facts = [fact for fact in facts if fact.document_id in matched_ids]
            if not product:
                facts = [fact for fact in facts if fact.product_id is None]
            if product_doc and product_doc.id in matched_ids:
                cited[product_doc.id] = product_doc
            parts = [_render_fact(fact, product_doc.title.split(":")[0] if product_doc else None)
                     for fact in facts]
            for fact in facts:
                cited[fact.document_id] = self.index.documents[fact.document_id]
            if len(mentioned) > 1:
                answer = "Здравствуйте! Уточните, пожалуйста, по какому из названных товаров нужны сведения."
                cited.clear()
                parts = []
            elif model_product:
                if product == "monitor" and _has(stems, {"экра"}):
                    size = next(iter(self.index.facts({"size"}, product)), None)
                    if size:
                        cited[product_doc.id] = product_doc
                        cited[size.document_id] = self.index.documents[size.document_id]
                    answer = (f"Здравствуйте! Для вашей задачи может подойти «{product_doc.title}»"
                              + (f" с диагональю {size.value}" if size else "")
                              + ". Такой размер вам подходит? Уточню условия после подтверждения модели.")
                else:
                    answer = (f"Здравствуйте! Возможно, вам подойдёт «{product_doc.title}». "
                              "Верно ли я понял, какой товар вас интересует? "
                              "После уточнения проверю подходящие условия.")
                    cited.clear()
            elif not parts:
                if needs_city:
                    answer = "Здравствуйте! Подскажите, пожалуйста, город доставки — уточню срок для вашего заказа."
                elif product_doc:
                    answer = (f"Здравствуйте! В нашем каталоге есть «{product_doc.title}». "
                              "Подскажите желаемый бюджет и важные требования — проверю, "
                              "насколько этот вариант подходит.")
                elif categories & {"price", "stock", "warranty", "ports", "size"}:
                    answer = ("Здравствуйте! По запрошенному товару сейчас нет подтверждённых "
                              "сведений в нашей базе. Уточню ассортимент и условия, затем "
                              "вернусь к вам с точным ответом.")
                else:
                    answer = ("Здравствуйте! Подскажите, пожалуйста, какой товар и для какой задачи "
                              "вы подбираете. Тогда смогу ответить точнее.")
            else:
                answer = "Здравствуйте! " + " ".join(parts)
                if any(fact.volatile for fact in facts):
                    answer += " Актуальность этих условий проверим перед подтверждением заказа."
                if needs_city:
                    answer += " Подскажите, пожалуйста, город доставки."
            tip, manager_source, stage = self._manager_tip(
                product, stems, intent, insight, model_product, bool(history))

        evidence = [Evidence(doc.id, doc.title, doc.source, doc.reviewed_at,
                             hit_scores.get(doc.id, 0.0)) for doc in cited.values()]
        manager_evidence = ([Evidence(manager_source.id, manager_source.title,
                                      manager_source.source, manager_source.reviewed_at, 0.0)]
                            if manager_source else [])
        retrieval_hits = [Evidence(hit.document.id, hit.document.title,
                                   hit.document.source, hit.document.reviewed_at, hit.bm25)
                          for hit in hits]
        mode = ("sqlite-bm25-aitunnel" if insight else
                "sqlite-bm25-context-rules" if context_used else "sqlite-bm25-rules")
        analysis = ({"intent": insight.intent, "product_id": insight.product_id,
                     "categories": sorted(insight.categories), "rule_id": insight.rule_id,
                     "need_quote": insight.need_quote, "need_summary": insight.need_summary,
                     "search_query": insight.search_query}
                    if insight else None)
        return Suggestion(answer, tip, evidence, manager_evidence, retrieval_hits, mode, True,
                          notice, product, stage, analysis)

    def _manager_tip(self, product: str | None, stems: set[str], intent: str,
                     insight: Insight | None, model_product: bool, has_history: bool
                     ) -> tuple[str, Document | None, str]:
        if intent != "sales":
            return "Допродажа сейчас неуместна.", None, "none"
        if not product:
            return ("Товар не определён однозначно. Сначала уточните, для какой задачи "
                    "клиент подбирает покупку; конкретное дополнение пока не предлагайте."), None, "clarify"
        rule = self.index.upsell(product)
        if not rule:
            return "Для этого товара в базе нет подтверждённого сценария допродажи.", None, "none"
        addon = self.index.documents.get(rule.add_on_id)
        if not addon:
            return "Сценарий допродажи неполон: товар-дополнение отсутствует в базе.", None, "none"
        if insight:
            if insight.rule_id == rule.id and insight.need_quote:
                lead = (f"Модель заметила возможную потребность: «{insight.need_quote}». "
                        f"Гипотеза: {insight.need_summary or rule.reason}\n")
                if model_product:
                    return (lead + f"Сначала подтвердите товар и спросите: «{rule.question}»\n"
                            "Дополнение пока не предлагайте как готовое решение."), addon, "clarify"
                return (lead + f"Дополнение из базы: {addon.title}.\nПочему подходит: {rule.reason}\n"
                        f"Вопрос менеджера: «{rule.question}»\n"
                        "Проверьте совместимость, цену и наличие перед предложением."), addon, "offer"
            if has_history:
                return ("Сначала ответьте на текущий вопрос клиента. В этой реплике нет "
                        "новой потребности в дополнении; не повторяйте предложение."), None, "none"
            return ("Сначала ответьте на вопрос клиента и уточните его задачу. Оснований "
                    "для конкретной допродажи пока нет."), None, "none"
        triggers = [set(tokens(term.strip())) for term in rule.trigger_terms.split(",")]
        if not any(trigger and trigger <= stems for trigger in triggers):
            return ("Ответьте на вопрос клиента и уточните сценарий использования. "
                    "Потребность в конкретном дополнении пока не подтверждена."), None, "clarify"
        return (("Клиент описал задачу, для которой может подойти дополнение.\n"
                f"Возможное дополнение: {addon.title}.\n"
                f"Почему: {rule.reason}\n"
                f"Вопрос менеджера: «{rule.question}»\n"
                "Перед предложением проверьте совместимость, цену и наличие. "
                "Если клиенту дополнение не нужно, не возвращайтесь к предложению."), addon, "offer")
