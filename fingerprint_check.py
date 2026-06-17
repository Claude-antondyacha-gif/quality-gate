#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fingerprint_check.py — Детектор AI-штампів у маркетингових текстах
Автор: Claude для Антона Дяченка
Методологія: Павло Антонов — живий, людський текст без робота

Перевірка тексту (UA + RU) на:
  1. AI-штампи — 24 найчастіші фрази-роботи    (вага: 40 балів)
  2. Канцеляризми                               (вага: 25 балів)
  3. Сухі висновки / резюме-кліше              (вага: 20 балів)
  4. Ритм і варіативність мови                 (вага: 15 балів)

Поріг публікації: 55/100
Якщо є корпоративний штамп → текст заблоковано
Пропонує 2-3 живих людських обороти для заміни
"""

import re
import sys
import json
import random
import argparse
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional


# ─────────────────────────────────────────────
#  БАНК AI-ШТАМПІВ (24 категорії)
# ─────────────────────────────────────────────

AI_STAMPS = [
    # ── Блок 1: Вступні кліше-зачіпки ──
    (r"в\s+(сучасному|сьогоднішньому|нинішньому)\s+світі?",
     "AI-вступ",
     ["Давай чесно:", "Ось що реально відбувається:", "Дивись, як це працює:"]),

    (r"в\s+(современном|сегодняшнем|нынешнем)\s+мире?",
     "AI-вступ (RU)",
     ["Честно говоря:", "Вот что реально происходит:", "Смотри, как это работает:"]),

    (r"(в\s+умовах|в\s+реаліях)\s+(сучасності|сьогодення|цифрової\s+епохи)",
     "AI-кліше «в умовах»",
     ["Зараз ситуація така:", "По факту:", "Якщо без прикрас —"]),

    (r"(в\s+условиях|в\s+реалиях)\s+(современности|сегодняшнего\s+дня|цифровой\s+эпохи)",
     "AI-кліше «в условиях» (RU)",
     ["Сейчас ситуация такая:", "По факту:", "Если без прикрас —"]),

    # ── Блок 2: Штампи важливості ──
    (r"це\s+(надзвичайно|вкрай|дуже)\s+(важливо|актуально|необхідно)",
     "AI-важливість",
     ["і ось чому це має значення:", "це змінює підхід:", "без цього — злив бюджету:"]),

    (r"это\s+(крайне|чрезвычайно|очень)\s+(важно|актуально|необходимо)",
     "AI-важливість (RU)",
     ["и вот почему это важно:", "это меняет подход:", "без этого — слив бюджета:"]),

    (r"не\s+можна\s+(недооцінювати|ігнорувати)\s+(важливість|роль|значення)",
     "AI-недооцінка",
     ["Пропустиш це — заплатиш двічі.", "Бачив таке сотні разів:", "Мій досвід каже:"]),

    (r"нельзя\s+(недооценивать|игнорировать)\s+(важность|роль|значение)",
     "AI-недооцінка (RU)",
     ["Пропустишь это — заплатишь дважды.", "Видел такое сотни раз:", "Мой опыт говорит:"]),

    # ── Блок 3: Штампи-висновки ──
    (r"(таким\s+чином|отже|підсумовуючи|підбиваючи\s+підсумки)[,.]?\s",
     "Сухий висновок",
     ["Коротко:", "Що з цього:", "Bottom line:"]),

    (r"(таким\s+образом|итак|подводя\s+итог|в\s+заключение)[,.]?\s",
     "Сухий висновок (RU)",
     ["Коротко:", "Что из этого:", "Bottom line:"]),

    (r"(варто\s+зазначити|слід\s+відмітити|необхідно\s+підкреслити)",
     "Канцелярський висновок",
     ["До речі —", "Важливий момент:", "Зверни увагу:"]),

    (r"(стоит\s+отметить|следует\s+подчеркнуть|необходимо\s+отметить)",
     "Канцелярський висновок (RU)",
     ["Кстати —", "Важный момент:", "Обрати внимание:"]),

    # ── Блок 4: Штампи переходів ──
    (r"говорячи\s+про\s+це[,.]",
     "AI-перехід",
     ["До речі,", "Ось тут і починається цікаве:", "І ще одне —"]),

    (r"говоря\s+об\s+этом[,.]",
     "AI-перехід (RU)",
     ["Кстати,", "Вот тут и начинается интересное:", "И ещё —"]),

    (r"(крім\s+того|більше\s+того|до\s+того\s+ж)[,]\s+(варто|слід|необхідно)",
     "AI-нанизування",
     ["Плюс до всього —", "І ось що ще:", "Окремий момент:"]),

    (r"(кроме\s+того|более\s+того|к\s+тому\s+же)[,]\s+(стоит|следует|необходимо)",
     "AI-нанизування (RU)",
     ["Плюс к этому —", "И вот ещё:", "Отдельный момент:"]),

    # ── Блок 5: Корпоративні штампи (БЛОКУЮЧІ) ──
    (r"(комплексний|комплексне|комплексна)\s+(підхід|рішення|обслуговування)",
     "⛔ КОРПОРАТИВНИЙ ШТАМП",
     ["конкретний план дій", "покрокова схема", "точна механіка"]),

    (r"(комплексный|комплексное|комплексная)\s+(подход|решение|обслуживание)",
     "⛔ КОРПОРАТИВНИЙ ШТАМП (RU)",
     ["конкретный план действий", "пошаговая схема", "точная механика"]),

    (r"(взаємовигідне|взаємовигідна|взаємовигідний)\s+(співробітництво|партнерство|співпраця)",
     "⛔ КОРПОРАТИВНИЙ ШТАМП",
     ["домовитись по справедливості", "чесна угода", "і тобі, і мені вигідно"]),

    (r"(взаимовыгодное|взаимовыгодная|взаимовыгодный)\s+(сотрудничество|партнёрство)",
     "⛔ КОРПОРАТИВНИЙ ШТАМП (RU)",
     ["договориться по-честному", "справедливая сделка", "и тебе, и мне выгодно"]),

    # ── Блок 6: AI-структури і перерахування ──
    (r"(по-перше|по-друге|по-третє)[,.]?\s.{10,}(по-перше|по-друге|по-третє)",
     "AI-нумерований список у тексті",
     ["Три речі:", "Ось що важливо:", "Коротко по пунктах —"]),

    (r"(во-первых|во-вторых|в-третьих)[,.]?\s.{10,}(во-первых|во-вторых|в-третьих)",
     "AI-нумерований список у тексті (RU)",
     ["Три вещи:", "Вот что важно:", "Кратко по пунктам —"]),

    # ── Блок 7: Штампи закликів ──
    (r"(зробіть\s+перший\s+крок|почніть\s+свій\s+шлях\s+до)",
     "AI-заклик",
     ["Перший крок — простий:", "Починається з одного рішення:", "Старт — ось тут:"]),

    (r"(сделайте\s+первый\s+шаг|начните\s+свой\s+путь\s+к)",
     "AI-заклик (RU)",
     ["Первый шаг — простой:", "Начинается с одного решения:", "Старт — вот здесь:"]),
]

# ─────────────────────────────────────────────
#  БАНК КАНЦЕЛЯРИЗМІВ
# ─────────────────────────────────────────────

BUREAUCRATIC_PATTERNS = [
    # UA
    (r"здійснювати\s+(заходи|дії|кроки)", "канцеляризм «здійснювати заходи»", "робити"),
    (r"проводити\s+(роботу|діяльність)", "канцеляризм «проводити роботу»", "працювати"),
    (r"забезпечувати\s+(потреби|запити)", "канцеляризм «забезпечувати потреби»", "давати те, що треба"),
    (r"реалізовувати\s+(проект|програму|стратегію)", "канцеляризм «реалізовувати»", "запускати / втілювати"),
    (r"(є\s+)?(невід'ємною|невід'ємним)\s+частиною", "канцеляризм «невід'ємна частина»", "завжди поряд / без цього ніяк"),
    (r"з\s+метою\s+(підвищення|покращення|забезпечення)", "канцеляризм «з метою»", "щоб"),
    (r"в\s+рамках\s+(проекту|програми|ініціативи)", "канцеляризм «в рамках»", "у межах / при"),
    (r"на\s+сьогоднішній\s+день", "канцеляризм «на сьогоднішній день»", "зараз / сьогодні"),
    (r"має\s+місце\s+(бути|знаходитись)", "канцеляризм «має місце бути»", "є / існує"),
    # RU
    (r"осуществлять\s+(меры|действия|шаги)", "канцеляризм «осуществлять меры»", "делать"),
    (r"проводить\s+(работу|деятельность)", "канцеляризм «проводить работу»", "работать"),
    (r"обеспечивать\s+(потребности|запросы)", "канцеляризм «обеспечивать потребности»", "давать то, что нужно"),
    (r"реализовывать\s+(проект|программу|стратегию)", "канцеляризм «реализовывать»", "запускать / воплощать"),
    (r"(является\s+)?неотъемлемой\s+частью", "канцеляризм «неотъемлемая часть»", "всегда рядом / без этого никак"),
    (r"с\s+целью\s+(повышения|улучшения|обеспечения)", "канцеляризм «с целью»", "чтобы"),
    (r"в\s+рамках\s+(проекта|программы|инициативы)", "канцеляризм «в рамках»", "в пределах / при"),
    (r"на\s+сегодняшний\s+день", "канцеляризм «на сегодняшний день»", "сейчас / сегодня"),
    (r"имеет\s+место\s+(быть|находиться)", "канцеляризм «имеет место быть»", "есть / существует"),
]

# ─────────────────────────────────────────────
#  БАНК ЖИВИХ ЛЮДСЬКИХ ОБОРОТІВ
# (для авто-підстановки у виправлений текст)
# ─────────────────────────────────────────────

HUMAN_PHRASES = {
    "opener": [
        "Якщо чесно —",
        "Ось що я помітив:",
        "Дивись, ось у чому річ:",
        "По факту виходить так:",
        "Скажу прямо:",
        "Знаєш, в чому нюанс?",
        "Це не очевидно, але —",
        "Я перевірив на собі:",
        "Чесно кажучи,",
        "Розкажу як є:",
        # RU
        "Если честно —",
        "Вот что я заметил:",
        "Смотри, вот в чём дело:",
        "По факту выходит так:",
        "Скажу прямо:",
        "Знаешь, в чём нюанс?",
        "Это не очевидно, но —",
        "Я проверил на себе:",
        "Честно говоря,",
        "Расскажу как есть:",
    ],
    "transition": [
        "І ось що важливо:",
        "Але є деталь:",
        "Тут починається цікаве:",
        "І тоді стало зрозуміло:",
        "Що мене вразило —",
        "А ось де більшість помиляється:",
        "Головний момент тут:",
        "Виявилось, що",
        # RU
        "И вот что важно:",
        "Но есть деталь:",
        "Тут начинается интересное:",
        "И тогда стало понятно:",
        "Что меня удивило —",
        "А вот где большинство ошибается:",
        "Главный момент здесь:",
        "Оказалось, что",
    ],
    "closer": [
        "Спробуй — і побачиш сам.",
        "Це реально змінює картину.",
        "Перевірено — працює.",
        "Деталь, яка вирішує всe.",
        "Ось так це і є.",
        "Простіше, ніж здається.",
        "Саме тому це і спрацьовує.",
        # RU
        "Попробуй — и увидишь сам.",
        "Это реально меняет картину.",
        "Проверено — работает.",
        "Деталь, которая решает всё.",
        "Вот так оно и есть.",
        "Проще, чем кажется.",
        "Именно поэтому это и работает.",
    ],
}

# ─────────────────────────────────────────────
#  СТРУКТУРИ ДАНИХ
# ─────────────────────────────────────────────

@dataclass
class StampMatch:
    pattern_label: str
    matched_text: str
    position: int
    is_corporate_block: bool
    suggestions: List[str]


@dataclass
class CriterionResult:
    name: str
    score: float
    weighted: float
    weight: float
    passed: bool
    details: str
    tips: List[str] = field(default_factory=list)
    matches: List[StampMatch] = field(default_factory=list)


@dataclass
class FingerprintReport:
    total_score: float
    passed: bool
    blocked_by_corporate: bool
    word_count: int
    sentence_count: int
    criteria: List[CriterionResult]
    all_stamps: List[StampMatch]
    human_suggestions: List[str]
    suggested_text: Optional[str] = None
    global_tips: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────
#  АНАЛІЗАТОРИ
# ─────────────────────────────────────────────

def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Zа-яА-ЯіІїЇєЄґҐ']+", text.lower())


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"[.!?…]+", text)
    return [p.strip() for p in parts if len(p.strip()) > 3]


def find_ai_stamps(text: str) -> Tuple[List[StampMatch], bool]:
    """Шукає AI-штампи. Повертає список збігів і флаг блокування."""
    found: List[StampMatch] = []
    blocked = False
    text_lower = text.lower()

    for pattern, label, suggestions in AI_STAMPS:
        for m in re.finditer(pattern, text_lower):
            is_corp = label.startswith("⛔")
            if is_corp:
                blocked = True
            found.append(StampMatch(
                pattern_label=label,
                matched_text=m.group(0),
                position=m.start(),
                is_corporate_block=is_corp,
                suggestions=suggestions,
            ))

    return found, blocked


def find_bureaucratic(text: str) -> List[Tuple[str, str, str]]:
    """Повертає список (знайдено, мітка, заміна)."""
    found = []
    text_lower = text.lower()
    for pattern, label, replacement in BUREAUCRATIC_PATTERNS:
        m = re.search(pattern, text_lower)
        if m:
            found.append((m.group(0), label, replacement))
    return found


def analyze_dry_conclusions(text: str) -> List[str]:
    """Визначає сухі, безживі висновкові речення."""
    DRY_PATTERNS = [
        r"(таким\s+чином|отже|підсумовуючи).{5,60}[.]",
        r"(таким\s+образом|итак|подводя\s+итог).{5,60}[.]",
        r"(можна\s+зробити\s+висновок|можно\s+сделать\s+вывод).{5,80}[.]",
        r"(з\s+вищесказаного|из\s+вышесказанного).{5,60}[.]",
        r"(резюмуючи|резюмируя).{5,60}[.]",
        r"це\s+свідчить\s+про\s+те,\s+що.{5,60}[.]",
        r"это\s+свидетельствует\s+о\s+том,\s+что.{5,60}[.]",
    ]
    found = []
    text_lower = text.lower()
    for p in DRY_PATTERNS:
        m = re.search(p, text_lower)
        if m:
            found.append(m.group(0))
    return found


def analyze_rhythm(sentences: List[str]) -> Tuple[float, str]:
    """
    Оцінює варіативність ритму: чи всі речення однакової довжини?
    Людський текст = різні довжини (короткі + довгі).
    """
    if not sentences:
        return 0.0, "Немає речень"

    lengths = [len(tokenize(s)) for s in sentences if tokenize(s)]
    if not lengths:
        return 0.0, "Не вдалося виміряти"

    avg = sum(lengths) / len(lengths)
    variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
    std = variance ** 0.5

    # Добрий ритм: стандартне відхилення > 3 (різноманітність)
    # AI-текст: всі речення ~10-12 слів, відхилення < 2
    if std >= 5:
        score = 100.0
        detail = f"Відмінний ритм (σ={std:.1f}): короткі і довгі речення чергуються"
    elif std >= 3:
        score = 75.0
        detail = f"Непоганий ритм (σ={std:.1f}): є різноманітність"
    elif std >= 1.5:
        score = 45.0
        detail = f"Монотонний ритм (σ={std:.1f}): речення занадто схожі за довжиною"
    else:
        score = 15.0
        detail = f"AI-ритм (σ={std:.1f}): всі речення однакові — ознака генерації"

    return score, detail


# ─────────────────────────────────────────────
#  СКОРИНГОВА ЛОГІКА
# ─────────────────────────────────────────────

def score_ai_stamps(stamps: List[StampMatch], word_count: int) -> Tuple[float, List[str]]:
    """
    0 штампів → 100
    1 штамп   → 70
    2 штампи  → 45
    3+        → 15
    Корпоративний штамп → окремий блок, але ще -15 до балу
    """
    tips = []
    corp_count = sum(1 for s in stamps if s.is_corporate_block)
    total = len(stamps)

    if total == 0:
        return 100.0, []
    elif total == 1:
        base = 70.0
    elif total == 2:
        base = 45.0
    elif total == 3:
        base = 25.0
    else:
        base = max(0.0, 15.0 - (total - 4) * 3)

    # Додатковий штраф за корпоративні
    score = max(0.0, base - corp_count * 15)

    for s in stamps:
        icon = "⛔" if s.is_corporate_block else "🤖"
        tip = (f"{icon} «{s.matched_text}» — {s.pattern_label}. "
               f"Заміни на: {' / '.join(s.suggestions[:2])}")
        tips.append(tip)

    return round(score, 1), tips


def score_bureaucratic(items: List[Tuple[str, str, str]]) -> Tuple[float, List[str]]:
    tips = []
    n = len(items)
    if n == 0:
        return 100.0, []
    elif n == 1:
        score = 65.0
    elif n == 2:
        score = 35.0
    else:
        score = 10.0

    for found, label, replacement in items:
        tips.append(f"📋 «{found}» — {label}. Простіша версія: «{replacement}»")

    return round(score, 1), tips


def score_dry_conclusions(items: List[str]) -> Tuple[float, List[str]]:
    tips = []
    n = len(items)
    if n == 0:
        return 100.0, []
    elif n == 1:
        score = 55.0
        tips.append(f"📎 Сухий висновок: «{items[0][:60]}…» — додай конкретику або емоцію")
    else:
        score = 20.0
        for item in items:
            tips.append(f"📎 «{item[:50]}…» — заміни на живий підсумок з цифрою або прикладом")
    return round(score, 1), tips


# ─────────────────────────────────────────────
#  ГЕНЕРАТОР ЖИВИХ ОБОРОТІВ
# ─────────────────────────────────────────────

def pick_human_phrases(count: int = 3) -> List[str]:
    """Вибирає N випадкових живих оборотів з трьох категорій."""
    result = []
    categories = ["opener", "transition", "closer"]
    for i, cat in enumerate(categories[:count]):
        phrase = random.choice(HUMAN_PHRASES[cat])
        result.append(f"[{cat.upper()}] {phrase}")
    return result


def suggest_improved_text(text: str, stamps: List[StampMatch],
                           bureaucratic: List[Tuple[str, str, str]]) -> str:
    """
    Повертає текст з підсвіченими проблемними місцями
    і пропозицією де вставити живі оберти.
    """
    result = text

    # Позначаємо AI-штампи
    for stamp in sorted(stamps, key=lambda s: s.position, reverse=True):
        original = re.compile(re.escape(stamp.matched_text), re.IGNORECASE)
        replacement = f"【❌ {stamp.matched_text} → {stamp.suggestions[0]}】"
        result = original.sub(replacement, result, count=1)

    # Позначаємо канцеляризми
    for found, label, replacement in bureaucratic:
        pattern = re.compile(re.escape(found), re.IGNORECASE)
        tagged = f"【📋 {found} → {replacement}】"
        result = pattern.sub(tagged, result, count=1)

    return result


# ─────────────────────────────────────────────
#  ГОЛОВНА ФУНКЦІЯ
# ─────────────────────────────────────────────

def analyze(text: str) -> FingerprintReport:
    text = text.strip()
    words = tokenize(text)
    sentences = split_sentences(text)

    if not words:
        raise ValueError("Текст порожній.")
    if len(words) < 15:
        raise ValueError(f"Текст занадто короткий ({len(words)} слів). Мінімум — 15.")

    # ── Критерій 1: AI-штампи (вага 40)
    stamps, blocked = find_ai_stamps(text)
    s1, t1 = score_ai_stamps(stamps, len(words))
    c1 = CriterionResult(
        name="AI-штампи",
        score=s1, weighted=s1 * 0.40, weight=40,
        passed=len(stamps) == 0,
        details=f"Знайдено {len(stamps)} штамп{'и' if 1 < len(stamps) < 5 else 'ів' if len(stamps) >= 5 else '' if len(stamps) == 0 else ''}",
        tips=t1, matches=stamps,
    )

    # ── Критерій 2: Канцеляризми (вага 25)
    bureaucratic = find_bureaucratic(text)
    s2, t2 = score_bureaucratic(bureaucratic)
    c2 = CriterionResult(
        name="Канцеляризми",
        score=s2, weighted=s2 * 0.25, weight=25,
        passed=len(bureaucratic) == 0,
        details=f"Знайдено {len(bureaucratic)} канцеляризм{'и' if 1 < len(bureaucratic) < 5 else 'ів' if len(bureaucratic) >= 5 else '' if len(bureaucratic) == 0 else ''}",
        tips=t2,
    )

    # ── Критерій 3: Сухі висновки (вага 20)
    dry = analyze_dry_conclusions(text)
    s3, t3 = score_dry_conclusions(dry)
    c3 = CriterionResult(
        name="Сухі висновки",
        score=s3, weighted=s3 * 0.20, weight=20,
        passed=len(dry) == 0,
        details=f"Знайдено {len(dry)} сухих висновк{'и' if 1 < len(dry) < 5 else 'ів' if len(dry) >= 5 else '' if len(dry) == 0 else ''}",
        tips=t3,
    )

    # ── Критерій 4: Ритм і варіативність (вага 15)
    rhythm_score, rhythm_detail = analyze_rhythm(sentences)
    rhythm_tips = []
    if rhythm_score < 50:
        rhythm_tips.append("🎵 Змішай довжини речень. Після довгого — коротке. «Ось результат.» «Три слова.» Потім знову розгорни думку.")
    s4 = rhythm_score
    c4 = CriterionResult(
        name="Ритм мови",
        score=s4, weighted=s4 * 0.15, weight=15,
        passed=rhythm_score >= 50,
        details=rhythm_detail,
        tips=rhythm_tips,
    )

    # ── Фінальний бал
    total = round(c1.weighted + c2.weighted + c3.weighted + c4.weighted, 1)

    # Блокування при наявності корпоративного штампу
    if blocked:
        total = min(total, 40.0)

    passed = total >= 55 and not blocked

    # ── Живі обороти
    human_suggestions = pick_human_phrases(3)

    # ── Підсвічений текст
    suggested = suggest_improved_text(text, stamps, bureaucratic) if not passed else None

    # ── Глобальні підказки
    global_tips: List[str] = []
    if not passed:
        global_tips += [
            "━" * 52,
            "🚫 ПУБЛІКАЦІЮ ЗАБЛОКОВАНО — текст звучить як AI" if not blocked
            else "⛔ ПУБЛІКАЦІЮ ЗАБЛОКОВАНО — корпоративний штамп",
            "━" * 52,
            "",
        ]
        if blocked:
            corp = [s for s in stamps if s.is_corporate_block]
            for s in corp:
                global_tips.append(f"⛔ Видали корпоративний штамп: «{s.matched_text}»")
                global_tips.append(f"   Заміни на: {' / '.join(s.suggestions)}")
            global_tips.append("")

        global_tips += [
            "✍️  ВСТАВ 2-3 ЖИВИХ ОБОРОТИ:",
            "",
        ]
        for phrase in human_suggestions:
            global_tips.append(f"   → {phrase}")

        global_tips += [
            "",
            "📋 ПЛАН ВИПРАВЛЕННЯ:",
        ]
        for c in sorted([c1, c2, c3, c4], key=lambda x: x.weighted):
            if not c.passed:
                global_tips.append(f"\n  [{c.name}] — {c.details}")
                for tip in c.tips:
                    global_tips.append(f"    {tip}")

        global_tips += ["", "🔁 Після правок — запусти скрипт знову."]

    return FingerprintReport(
        total_score=total,
        passed=passed,
        blocked_by_corporate=blocked,
        word_count=len(words),
        sentence_count=len(sentences),
        criteria=[c1, c2, c3, c4],
        all_stamps=stamps,
        human_suggestions=human_suggestions,
        suggested_text=suggested,
        global_tips=global_tips,
    )


# ─────────────────────────────────────────────
#  ФОРМАТУВАННЯ ВИВОДУ
# ─────────────────────────────────────────────

COLORS = {
    "green":  "\033[92m", "yellow": "\033[93m",
    "red":    "\033[91m", "cyan":   "\033[96m",
    "purple": "\033[95m", "bold":   "\033[1m",
    "reset":  "\033[0m",  "dim":    "\033[2m",
}


def c(text: str, *codes: str, nc: bool = False) -> str:
    if nc:
        return text
    return "".join(COLORS.get(x, "") for x in codes) + text + COLORS["reset"]


def score_bar(score: float, width: int = 20, nc: bool = False) -> str:
    filled = int(score / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    col = "green" if score >= 75 else "yellow" if score >= 50 else "red"
    return c(bar, col, nc=nc)


def score_fmt(score: float, nc: bool = False) -> str:
    col = "green" if score >= 75 else "yellow" if score >= 50 else "red"
    return c(f"{score:.1f}", col, "bold", nc=nc)


def print_report(report: FingerprintReport, nc: bool = False,
                 show_text: bool = True) -> None:
    print()
    print(c("╔══════════════════════════════════════════════════════╗", "purple", nc=nc))
    print(c("║       FINGERPRINT CHECK — ДЕТЕКТОР AI-ШТАМПІВ       ║", "purple", nc=nc))
    print(c("╚══════════════════════════════════════════════════════╝", "purple", nc=nc))
    print()
    print(f"  Слів: {report.word_count}   |   Речень: {report.sentence_count}")
    print()

    print(c("  КРИТЕРІЇ:", "bold", nc=nc))
    print(c("  " + "─" * 54, "dim", nc=nc))
    for cr in report.criteria:
        icon = "✅" if cr.passed else "❌"
        print(f"  {icon}  {cr.name:<26} {score_bar(cr.score, nc=nc)} {score_fmt(cr.score, nc=nc)}/100  (×{cr.weight}%)")
        print(f"      {c(cr.details, 'dim', nc=nc)}")
        print()

    print(c("  " + "─" * 54, "dim", nc=nc))

    if report.blocked_by_corporate:
        verdict = c("  ⛔  ЗАБЛОКОВАНО — КОРПОРАТИВНИЙ ШТАМП", "red", "bold", nc=nc)
    elif report.passed:
        verdict = c("  ✅  ПУБЛІКАЦІЮ ДОЗВОЛЕНО", "green", "bold", nc=nc)
    else:
        verdict = c("  🚫  ПУБЛІКАЦІЮ ЗАБЛОКОВАНО", "red", "bold", nc=nc)

    print(f"{verdict}   |   Бал: {score_fmt(report.total_score, nc=nc)} / 100")
    print(c("  " + "═" * 54, "dim", nc=nc))
    print()

    # Живі обороти — завжди показуємо
    print(c("  ✍️  ЖИВІ ЛЮДСЬКІ ОБОРОТИ для цього тексту:", "cyan", "bold", nc=nc))
    for phrase in report.human_suggestions:
        print(f"      → {phrase}")
    print()

    # Підказки якщо не пройшло
    if not report.passed:
        for line in report.global_tips:
            print(f"  {line}")
        print()

    # Підсвічений текст з позначками
    if show_text and report.suggested_text and not report.passed:
        print(c("  📝 ТЕКСТ З ПОЗНАЧКАМИ:", "yellow", "bold", nc=nc))
        print(c("  " + "─" * 54, "dim", nc=nc))
        # Виводимо по 80 символів
        for line in report.suggested_text.split("\n"):
            print(f"  {line}")
        print()

    if report.passed and report.total_score >= 80:
        print(c("  🎉 Чистий текст! Звучить по-людськи — можна публікувати.", "green", nc=nc))
        print()


def report_to_dict(report: FingerprintReport) -> Dict:
    return {
        "total_score": report.total_score,
        "passed": report.passed,
        "blocked_by_corporate": report.blocked_by_corporate,
        "word_count": report.word_count,
        "sentence_count": report.sentence_count,
        "criteria": [
            {"name": c.name, "score": c.score, "weighted": c.weighted,
             "passed": c.passed, "details": c.details, "tips": c.tips}
            for c in report.criteria
        ],
        "stamps_found": [
            {"label": s.pattern_label, "text": s.matched_text,
             "is_corporate": s.is_corporate_block, "suggestions": s.suggestions}
            for s in report.all_stamps
        ],
        "human_suggestions": report.human_suggestions,
        "suggested_text": report.suggested_text,
        "global_tips": [t for t in report.global_tips if t],
    }


# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="fingerprint_check.py — детектор AI-штампів у текстах UA/RU",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ПРИКЛАДИ:
  python3 fingerprint_check.py -t "Текст для перевірки"
  python3 fingerprint_check.py -f post.txt
  cat post.txt | python3 fingerprint_check.py
  python3 fingerprint_check.py -f post.txt --json
  python3 fingerprint_check.py -f post.txt --no-text
        """,
    )
    parser.add_argument("-t", "--text", help="Текст рядком")
    parser.add_argument("-f", "--file", help="Шлях до файлу")
    parser.add_argument("--json", action="store_true", help="JSON-вивід")
    parser.add_argument("--no-color", action="store_true", help="Без кольорів")
    parser.add_argument("--no-text", action="store_true",
                        help="Не показувати підсвічений текст")
    parser.add_argument("--min-score", type=float, default=55,
                        help="Мінімальний бал (за замовчуванням: 55)")
    args = parser.parse_args()

    if args.text:
        text = args.text
    elif args.file:
        try:
            with open(args.file, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            print(f"❌ Файл не знайдено: {args.file}", file=sys.stderr)
            sys.exit(2)
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        print("❌ Вкажи текст: -t 'текст', -f файл.txt або stdin", file=sys.stderr)
        parser.print_help()
        sys.exit(2)

    try:
        report = analyze(text)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(report_to_dict(report), ensure_ascii=False, indent=2))
    else:
        print_report(report, nc=args.no_color, show_text=not args.no_text)

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
