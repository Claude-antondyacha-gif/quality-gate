#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reel_analyzer.py — Аналіз вірусних рілсів і адаптація в сценарії
Автор: Claude для Антона Дяченка (@anton_dyacha)

Що робить:
  analyze   — аналізує рілс за URL або описом через Claude API
  style     — показує поточний Style Guide Антона
  scenario  — генерує сценарій рілса з урахуванням Style Guide
  sync      — синхронізує папку inspiration з Google Drive і аналізує нові відео
  report    — зведений звіт по всіх проаналізованих рілсах

Зберігає:
  style_guide.json   — твій особистий ДНК-стиль (накопичується)
  reel_insights.json — база проаналізованих рілсів
"""

import json
import sys
import re
import argparse
import urllib.request
import urllib.error
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List, Dict


# ─────────────────────────────────────────────
#  КОНФІГ
# ─────────────────────────────────────────────

BASE_DIR   = Path(__file__).parent
STYLE_FILE = BASE_DIR / "style_guide.json"
DB_FILE    = BASE_DIR / "reel_insights.json"
API_URL    = "https://api.anthropic.com/v1/messages"
MODEL      = "claude-sonnet-4-6"

COLORS = {
    "green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m",
    "cyan": "\033[96m",  "purple": "\033[95m", "bold": "\033[1m",
    "reset": "\033[0m",  "dim": "\033[2m",
}

def c(text, *codes, nc=False):
    if nc: return text
    return "".join(COLORS.get(x,"") for x in codes) + text + COLORS["reset"]


# ─────────────────────────────────────────────
#  INITIAL STYLE GUIDE (стартовий профіль Антона)
# ─────────────────────────────────────────────

DEFAULT_STYLE = {
    "meta": {
        "created": str(date.today()),
        "updated": str(date.today()),
        "total_analyzed": 0,
        "instagram": "anton_dyacha",
        "niche": "digital marketing / особистий бренд"
    },
    "voice": {
        "tone": "живий, прямий, без пафосу — як розмова з колегою",
        "language": "українська (основна), природні суржик-обороти ок",
        "avoid": [
            "AI-штампи і кліше",
            "корпоративні формулювання",
            "навчальний тон зверху вниз",
            "зайві пояснення і підводки"
        ],
        "use": [
            "конкретні цифри і факти",
            "особистий досвід від першої особи",
            "провокативні питання як хуки",
            "коротке і рубане перше речення"
        ]
    },
    "hooks": {
        "preferred_types": [
            "провокативне твердження",
            "цифра + несподіваний факт",
            "питання що дражнить",
            "помилка яку всі роблять"
        ],
        "duration_sec": "0–3 секунди вирішують все",
        "examples": []
    },
    "structure": {
        "ideal_duration": "15–45 секунд",
        "pacing": "швидкий монтаж, кожна думка — один кадр",
        "transitions": "різкі cut, без плавних переходів",
        "text_on_screen": "короткі субтитри або ключова фраза великим шрифтом",
        "cta_style": "природній, не нав'язливий — наприкінці або в субтитрах"
    },
    "visual": {
        "preferred_formats": ["talking head", "b-roll з закадровим текстом", "screen recording з коментарем"],
        "energy": "середньо-висока, живий рух камери або жести",
        "background": "реальне середовище (кафе, офіс, місто) — не студійний фон",
        "caption_style": "великий шрифт, мінімум слів, контрастний колір"
      },
    "content_pillars": [
        {
            "name": "Маркетингові інсайти",
            "description": "Конкретні тактики Meta/TikTok з цифрами. Без води.",
            "frequency": "40%"
        },
        {
            "name": "Особистий досвід",
            "description": "Кейси з реальних проектів — що спрацювало, що ні",
            "frequency": "30%"
        },
        {
            "name": "Провокація і думка",
            "description": "Суперечливий погляд на індустрію. Те що більшість не каже.",
            "frequency": "20%"
        },
        {
            "name": "Процес і за лаштунками",
            "description": "Як виглядає робота зсередини. Без прикрас.",
            "frequency": "10%"
        }
    ],
    "inspiration_patterns": [],
    "scenario_rules": [
        "Перша фраза — не більше 7 слів",
        "Жодних підводок типу 'Сьогодні я розповім...'",
        "Кожна сцена = одна думка = максимум 5 секунд",
        "Завжди є конкретний takeaway — що глядач може зробити одразу",
        "CTA органічний — не 'підпишись', а дія пов'язана з темою"
    ]
}


# ─────────────────────────────────────────────
#  ЗАВАНТАЖЕННЯ / ЗБЕРЕЖЕННЯ
# ─────────────────────────────────────────────

def load_style() -> dict:
    if STYLE_FILE.exists():
        with open(STYLE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_STYLE.copy()


def save_style(style: dict):
    style["meta"]["updated"] = str(date.today())
    with open(STYLE_FILE, "w", encoding="utf-8") as f:
        json.dump(style, f, ensure_ascii=False, indent=2)


def load_db() -> dict:
    if DB_FILE.exists():
        with open(DB_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"reels": [], "total": 0}


def save_db(db: dict):
    db["total"] = len(db["reels"])
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
#  CLAUDE API
# ─────────────────────────────────────────────

def call_claude(prompt: str, system: str = "", max_tokens: int = 1000) -> str:
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }
    if system:
        payload["system"] = system

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["content"][0]["text"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"API error {e.code}: {body}")


# ─────────────────────────────────────────────
#  АНАЛІЗ РІЛСА
# ─────────────────────────────────────────────

ANALYSIS_SYSTEM = """Ти — аналітик вірусного відеоконтенту з досвідом у digital marketing.
Аналізуєш чому рілс набрав перегляди: хук, структура, ритм, подача, текст, візуал.
Відповідаєш структуровано, конкретно, без води. Мова — українська."""

ANALYSIS_PROMPT_TEMPLATE = """Проаналізуй цей рілс і поверни ТІЛЬКИ JSON без жодного тексту поза ним.

Джерело: {source}
Опис/контекст: {description}
Платформа: {platform}
Ніша: digital marketing / особистий бренд маркетолога

JSON структура:
{{
  "id": "унікальний slug з назви/теми",
  "source": "{source}",
  "platform": "{platform}",
  "analyzed_date": "{today}",
  "why_viral": {{
    "hook": "що саме у перших 3 секундах зупиняє скрол",
    "hook_type": "тип хука: цифра/провокація/питання/помилка/таємниця",
    "structure": "як побудований рілс (акт 1-2-3 або інша структура)",
    "pacing": "швидкий/середній/повільний, ритм монтажу",
    "emotional_trigger": "яка емоція активується: страх/цікавість/натхнення/впізнавання/злість",
    "key_insight": "головна думка яку глядач забирає з собою",
    "cta": "як і де заклик до дії"
  }},
  "visual": {{
    "format": "talking head / b-roll / screen / змішаний",
    "energy": "1-10 де 10 = максимально енергійно",
    "text_on_screen": "як використовується текст на екрані",
    "editing_style": "опис стилю монтажу"
  }},
  "adapt_for_anton": {{
    "can_steal": ["конкретний прийом 1", "конкретний прийом 2"],
    "hook_rewrite": "переписаний хук адаптований під нішу Антона (маркетинг/особистий бренд)",
    "scenario_idea": "конкретна ідея рілса для Антона на основі цього рілса",
    "avoid": "що НЕ брати — не підходить під стиль або нішу"
  }},
  "score": {{
    "hook_strength": "1-10",
    "structure_clarity": "1-10",
    "adaptability": "1-10",
    "total": "середнє з трьох"
  }},
  "tags": ["тег1", "тег2", "тег3"]
}}"""


def analyze_reel(source: str, description: str = "",
                 platform: str = "instagram", nc: bool = False) -> dict:
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        source=source,
        description=description or "не вказано",
        platform=platform,
        today=str(date.today()),
    )

    print(c(f"\n  🔍 Аналізую рілс: {source[:60]}...", "cyan", nc=nc))
    print(c("  ⏳ Запит до Claude API...\n", "dim", nc=nc))

    raw = call_claude(prompt, system=ANALYSIS_SYSTEM, max_tokens=1200)

    # Парсимо JSON з відповіді
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        raise ValueError(f"Не вдалось розпарсити JSON з відповіді:\n{raw[:300]}")

    return json.loads(json_match.group(0))


# ─────────────────────────────────────────────
#  ОНОВЛЕННЯ STYLE GUIDE
# ─────────────────────────────────────────────

def update_style_from_analysis(style: dict, analysis: dict) -> dict:
    """Витягує паттерни з аналізу і додає в Style Guide."""
    why = analysis.get("why_viral", {})
    adapt = analysis.get("adapt_for_anton", {})

    # Додаємо хук у приклади якщо сильний
    hook_score = float(analysis.get("score", {}).get("hook_strength", 0))
    if hook_score >= 8:
        example = {
            "hook": why.get("hook", ""),
            "type": why.get("hook_type", ""),
            "source": analysis.get("source", ""),
            "rewrite": adapt.get("hook_rewrite", ""),
        }
        existing_hooks = [h.get("hook") for h in style["hooks"]["examples"]]
        if example["hook"] not in existing_hooks:
            style["hooks"]["examples"].append(example)
            # Тримаємо тільки топ-20 хуків
            style["hooks"]["examples"] = style["hooks"]["examples"][-20:]

    # Додаємо паттерн в inspiration
    pattern = {
        "date": str(date.today()),
        "source": analysis.get("source", ""),
        "emotional_trigger": why.get("emotional_trigger", ""),
        "structure": why.get("structure", ""),
        "can_steal": adapt.get("can_steal", []),
        "scenario_idea": adapt.get("scenario_idea", ""),
    }
    style["inspiration_patterns"].append(pattern)
    style["inspiration_patterns"] = style["inspiration_patterns"][-50:]

    style["meta"]["total_analyzed"] = style["meta"].get("total_analyzed", 0) + 1
    return style


# ─────────────────────────────────────────────
#  ГЕНЕРАЦІЯ СЦЕНАРІЮ
# ─────────────────────────────────────────────

SCENARIO_SYSTEM = """Ти — сценарист відео-контенту для особистого бренду.
Пишеш живі, конкретні сценарії без AI-кліше і шаблонів.
Враховуєш Style Guide автора. Мова — українська."""

def generate_scenario(topic: str, style: dict,
                       duration: int = 30, nc: bool = False) -> str:
    # Витягуємо ключові елементи стилю
    voice = style.get("voice", {})
    hooks = style.get("hooks", {})
    structure = style.get("structure", {})
    visual = style.get("visual", {})
    rules = style.get("scenario_rules", [])
    patterns = style.get("inspiration_patterns", [])

    # Топ-3 нещодавніх паттерни
    recent_patterns = patterns[-3:] if patterns else []
    patterns_str = "\n".join(
        f"  - [{p.get('source','')}]: {p.get('scenario_idea','')}"
        for p in recent_patterns
    ) or "  немає ще"

    # Топ хуки
    top_hooks = hooks.get("examples", [])[-5:]
    hooks_str = "\n".join(
        f"  - [{h.get('type','')}] {h.get('rewrite', h.get('hook',''))}"
        for h in top_hooks
    ) or "  немає ще"

    prompt = f"""Напиши детальний сценарій рілса для Instagram (@anton_dyacha).

ТЕМА: {topic}
ТРИВАЛІСТЬ: ~{duration} секунд

STYLE GUIDE АНТОНА:
Голос: {voice.get('tone', '')}
Уникати: {', '.join(voice.get('avoid', []))}
Використовувати: {', '.join(voice.get('use', []))}
Ідеальна тривалість: {structure.get('ideal_duration', '')}
Пейсинг: {structure.get('pacing', '')}
Переходи: {structure.get('transitions', '')}
Текст на екрані: {structure.get('text_on_screen', '')}
Візуал: {', '.join(visual.get('preferred_formats', []))}
Фон: {visual.get('background', '')}

ПРАВИЛА СЦЕНАРІЮ:
{chr(10).join(f"- {r}" for r in rules)}

ХУКИ ЯКІ ВЖЕ ДОБРЕ ВІДПРАЦЮВАЛИ (використай схожі):
{hooks_str}

ПАТТЕРНИ З ПРОАНАЛІЗОВАНИХ РІЛСІВ:
{patterns_str}

СТРУКТУРА ВІДПОВІДІ (тільки це, без вступу):

🎬 СЦЕНАРІЙ: [назва]
⏱ Тривалість: {duration} сек

---
ХУК (0-3 сек):
[текст що говориш / показуєш]
[текст на екрані якщо є]
[дія камери / візуал]

РОЗВИТОК (4-{duration-8} сек):
СЦЕНА 1 (X сек): [текст] | [візуал] | [текст на екрані]
СЦЕНА 2 (X сек): [текст] | [візуал] | [текст на екрані]
...

ФІНАЛ + CTA ({duration-7}-{duration} сек):
[текст] | [візуал] | [CTA]

---
📝 ПІДПИС ДО ПОСТУ:
[готовий текст поста 3-5 речень]

🏷 ХЕШТЕГИ:
[5-7 хештегів]

🎯 ПРОМПТ ДЛЯ HIGGSFIELD:
[опис відео для генерації в Higgsfield якщо потрібні AI-сцени]

📁 МАТЕРІАЛ З DRIVE:
[що шукати в папці anton_brand/raw для цього рілса]"""

    print(c(f"\n  ✍️  Генерую сценарій для: {topic[:50]}...", "cyan", nc=nc))
    print(c("  ⏳ Запит до Claude API...\n", "dim", nc=nc))

    return call_claude(prompt, system=SCENARIO_SYSTEM, max_tokens=1500)


# ─────────────────────────────────────────────
#  ВИВІД АНАЛІЗУ
# ─────────────────────────────────────────────

def print_analysis(analysis: dict, nc: bool = False):
    why = analysis.get("why_viral", {})
    adapt = analysis.get("adapt_for_anton", {})
    score = analysis.get("score", {})
    visual = analysis.get("visual", {})

    print()
    print(c("╔══════════════════════════════════════════════════════╗", "purple", nc=nc))
    print(c("║            REEL ANALYZER — РОЗБІР РІЛСА             ║", "purple", nc=nc))
    print(c("╚══════════════════════════════════════════════════════╝", "purple", nc=nc))
    print()

    print(c(f"  Джерело: ", "dim", nc=nc) + analysis.get("source", "—"))
    print(c(f"  Платформа: ", "dim", nc=nc) + analysis.get("platform", "—"))
    print(c(f"  Дата: ", "dim", nc=nc) + analysis.get("analyzed_date", "—"))
    print()

    # Скор
    total = score.get("total", "—")
    hook_s = score.get("hook_strength", "—")
    struct_s = score.get("structure_clarity", "—")
    adapt_s = score.get("adaptability", "—")

    print(c("  ОЦІНКИ:", "bold", nc=nc))
    print(f"  Хук: {c(str(hook_s), 'green', nc=nc)}/10   "
          f"Структура: {c(str(struct_s), 'green', nc=nc)}/10   "
          f"Адаптивність: {c(str(adapt_s), 'green', nc=nc)}/10   "
          f"| Загальна: {c(str(total), 'yellow', 'bold', nc=nc)}/10")
    print()

    # Чому залетів
    print(c("  ЧОМУ ЗАЛЕТІВ:", "bold", nc=nc))
    print(c("  ─────────────────────────────────────────────────────", "dim", nc=nc))
    print(f"  🎣 Хук ({why.get('hook_type','')}):")
    print(f"     {why.get('hook','—')}")
    print()
    print(f"  🏗  Структура: {why.get('structure','—')}")
    print(f"  ⚡ Пейсинг: {why.get('pacing','—')}")
    print(f"  💡 Емоційний тригер: {why.get('emotional_trigger','—')}")
    print(f"  🎯 Ключова думка: {why.get('key_insight','—')}")
    print(f"  📣 CTA: {why.get('cta','—')}")
    print()

    # Візуал
    print(c("  ВІЗУАЛ:", "bold", nc=nc))
    print(f"  Формат: {visual.get('format','—')} | Енергія: {visual.get('energy','—')}/10")
    print(f"  Текст: {visual.get('text_on_screen','—')}")
    print(f"  Монтаж: {visual.get('editing_style','—')}")
    print()

    # Адаптація
    print(c("  ЩО БЕРЕМО ДЛЯ АНТОНА:", "bold", nc=nc))
    print(c("  ─────────────────────────────────────────────────────", "dim", nc=nc))
    for steal in adapt.get("can_steal", []):
        print(f"  ✅ {steal}")
    print()
    print(f"  🔄 Хук переписаний під нішу:")
    print(c(f"     «{adapt.get('hook_rewrite','—')}»", "green", nc=nc))
    print()
    print(f"  💡 Ідея рілса для Антона:")
    print(f"     {adapt.get('scenario_idea','—')}")
    print()
    print(f"  ❌ Не брати: {adapt.get('avoid','—')}")
    print()

    tags = " ".join(f"#{t}" for t in analysis.get("tags", []))
    print(c(f"  {tags}", "dim", nc=nc))
    print()


# ─────────────────────────────────────────────
#  ЗВІТ
# ─────────────────────────────────────────────

def print_report(nc: bool = False):
    db = load_db()
    style = load_style()
    reels = db.get("reels", [])

    print()
    print(c("  📊 ЗВІТ — БАЗА ПРОАНАЛІЗОВАНИХ РІЛСІВ", "cyan", "bold", nc=nc))
    print(c("  " + "─" * 54, "dim", nc=nc))
    print(f"\n  Всього: {len(reels)} рілсів | Style Guide оновлено: {style['meta'].get('updated','—')}")
    print()

    if not reels:
        print(c("  Поки порожньо. Додай перший рілс: `reel_analyzer.py analyze --url ...`", "dim", nc=nc))
        return

    # Топ по загальній оцінці
    sorted_reels = sorted(
        reels,
        key=lambda r: float(r.get("score", {}).get("total", 0)),
        reverse=True
    )

    print(c("  ТОП РІЛСІВ ЗА ОЦІНКОЮ:", "bold", nc=nc))
    for i, r in enumerate(sorted_reels[:5], 1):
        score = r.get("score", {}).get("total", "—")
        hook_type = r.get("why_viral", {}).get("hook_type", "—")
        print(f"  {i}. {c(str(score), 'yellow', nc=nc)}/10  [{hook_type}]  {r.get('source','')[:55]}")
        idea = r.get("adapt_for_anton", {}).get("scenario_idea", "")
        if idea:
            print(c(f"     → {idea[:70]}…", "dim", nc=nc))
    print()

    # Паттерни хуків
    hook_types: Dict[str, int] = {}
    triggers: Dict[str, int] = {}
    for r in reels:
        ht = r.get("why_viral", {}).get("hook_type", "інше")
        hook_types[ht] = hook_types.get(ht, 0) + 1
        et = r.get("why_viral", {}).get("emotional_trigger", "інше")
        triggers[et] = triggers.get(et, 0) + 1

    print(c("  ПОПУЛЯРНІ ТИПИ ХУКІВ:", "bold", nc=nc))
    for ht, cnt in sorted(hook_types.items(), key=lambda x: -x[1]):
        print(f"  {'█' * cnt:<6} {ht} ({cnt}x)")
    print()

    print(c("  ЕМОЦІЙНІ ТРИГЕРИ:", "bold", nc=nc))
    for et, cnt in sorted(triggers.items(), key=lambda x: -x[1]):
        print(f"  {'█' * cnt:<6} {et} ({cnt}x)")
    print()

    # Ідеї що ще не реалізовані
    print(c("  НЕВИКОРИСТАНІ ІДЕЇ СЦЕНАРІЇВ:", "bold", nc=nc))
    for r in sorted_reels:
        idea = r.get("adapt_for_anton", {}).get("scenario_idea", "")
        if idea:
            print(f"  → {idea[:75]}")
    print()


# ─────────────────────────────────────────────
#  ПОКАЗ STYLE GUIDE
# ─────────────────────────────────────────────

def print_style(nc: bool = False):
    style = load_style()
    print()
    print(c("  🎨 STYLE GUIDE @anton_dyacha", "purple", "bold", nc=nc))
    print(c("  " + "─" * 54, "dim", nc=nc))
    print(f"\n  Проаналізовано рілсів: {style['meta'].get('total_analyzed', 0)}")
    print(f"  Оновлено: {style['meta'].get('updated','—')}")
    print()

    voice = style.get("voice", {})
    print(c("  ГОЛОС:", "bold", nc=nc))
    print(f"  {voice.get('tone','')}")
    print(f"\n  Уникати: {', '.join(voice.get('avoid',[]))}")
    print(f"  Використовувати: {', '.join(voice.get('use',[]))}")
    print()

    print(c("  СТРУКТУРА РІЛСА:", "bold", nc=nc))
    struct = style.get("structure", {})
    print(f"  Тривалість: {struct.get('ideal_duration','')} | Пейсинг: {struct.get('pacing','')}")
    print(f"  Переходи: {struct.get('transitions','')}")
    print()

    print(c("  ПРАВИЛА СЦЕНАРІЮ:", "bold", nc=nc))
    for rule in style.get("scenario_rules", []):
        print(f"  • {rule}")
    print()

    hooks = style.get("hooks", {}).get("examples", [])
    if hooks:
        print(c(f"  ХУКИ З БАЗИ ({len(hooks)}):", "bold", nc=nc))
        for h in hooks[-5:]:
            print(f"  [{h.get('type','')}] {c(h.get('rewrite', h.get('hook','')), 'green', nc=nc)}")
        print()

    pillars = style.get("content_pillars", [])
    print(c("  КОНТЕНТ-ПІЛОНИ:", "bold", nc=nc))
    for p in pillars:
        print(f"  {p.get('frequency','')} — {p.get('name','')}: {p.get('description','')}")
    print()


# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="reel_analyzer.py — аналіз вірусних рілсів і генерація сценаріїв",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
КОМАНДИ:
  analyze   — аналізує рілс і зберігає в базу
  scenario  — генерує сценарій з урахуванням Style Guide
  style     — показує поточний Style Guide
  report    — зведений звіт по всіх рілсах

ПРИКЛАДИ:
  python3 reel_analyzer.py analyze --url "https://instagram.com/reel/..." --desc "talking head про Meta Ads, хук - цифра CPM"
  python3 reel_analyzer.py analyze --desc "Рілс без URL: людина в кафе, хук - 'ніхто не говорить про це', тема - алгоритм TikTok"
  python3 reel_analyzer.py scenario --topic "Чому я не рекламую курс — я рекламую стабільність"
  python3 reel_analyzer.py scenario --topic "Meta Andromeda: таргетинг помер" --duration 45
  python3 reel_analyzer.py style
  python3 reel_analyzer.py report
        """,
    )
    parser.add_argument("command",
                        choices=["analyze", "scenario", "style", "report"],
                        help="Команда")
    parser.add_argument("--url", default="", help="URL рілса")
    parser.add_argument("--desc", default="", help="Опис рілса (що бачиш, що чуєш)")
    parser.add_argument("--platform", default="instagram", help="Платформа (instagram/tiktok/youtube)")
    parser.add_argument("--topic", default="", help="Тема для генерації сценарію")
    parser.add_argument("--duration", type=int, default=30, help="Тривалість рілса в секундах")
    parser.add_argument("--no-color", action="store_true", help="Без кольорів")

    args = parser.parse_args()
    nc = args.no_color

    if args.command == "analyze":
        source = args.url or args.desc[:60] or "manual_input"
        if not args.url and not args.desc:
            print("❌ Вкажи --url або --desc рілса", file=sys.stderr)
            sys.exit(2)

        analysis = analyze_reel(
            source=args.url or "без URL",
            description=args.desc,
            platform=args.platform,
            nc=nc
        )

        print_analysis(analysis, nc=nc)

        # Зберігаємо в базу
        db = load_db()
        db["reels"].append(analysis)
        save_db(db)

        # Оновлюємо Style Guide
        style = load_style()
        style = update_style_from_analysis(style, analysis)
        save_style(style)

        print(c("  ✅ Збережено в базу і Style Guide оновлено.", "green", nc=nc))
        print()

    elif args.command == "scenario":
        if not args.topic:
            print("❌ Вкажи --topic тему сценарію", file=sys.stderr)
            sys.exit(2)

        style = load_style()
        scenario = generate_scenario(
            topic=args.topic,
            style=style,
            duration=args.duration,
            nc=nc
        )

        print()
        print(c("╔══════════════════════════════════════════════════════╗", "purple", nc=nc))
        print(c("║                  ГОТОВИЙ СЦЕНАРІЙ                   ║", "purple", nc=nc))
        print(c("╚══════════════════════════════════════════════════════╝", "purple", nc=nc))
        print()
        print(scenario)
        print()

    elif args.command == "style":
        print_style(nc=nc)

    elif args.command == "report":
        print_report(nc=nc)


if __name__ == "__main__":
    main()
