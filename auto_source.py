#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_source.py — Розумний підбір тем з бази ідей
Автор: Claude для Антона Дяченка
Методологія: Павло Антонов — data-driven контент без повторів

Функції:
  top5      — вивести топ-5 тем для роботи сьогодні
  publish   — позначити тему як опубліковану (оновлює звіт)
  add       — додати нову ідею в базу
  log       — показати журнал публікацій
  stats     — статистика по напрямках і CTA
  replenish — поповнити базу новими темами з research scout

Правила антиповтору:
  - Один напрямок не частіше 1 разу в 4 дні
  - Один CTA не частіше 1 разу в 2 дні
  - Тема повторюється лише через 30 днів

Скоринг (0-30 балів):
  simplicity  0-10 — наскільки просто пояснити / зняти
  originality 0-10 — унікальність джерела / кута зору
  relevance   0-10 — актуальність прямо зараз
  + бонус за свіжість і актуальність джерела
"""

import json
import sys
import argparse
import os
import random
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Tuple
from pathlib import Path


# ─────────────────────────────────────────────
#  КОНФІГ
# ─────────────────────────────────────────────

DB_PATH = Path(__file__).parent / "ideas_db.json"
REPORT_PATH = Path(__file__).parent / "publish_report.md"

DIRECTION_LABELS = {
    "meta_ads":       "Meta Ads",
    "tiktok_ads":     "TikTok Ads",
    "lead_gen":       "Lead Generation",
    "real_estate":    "Real Estate",
    "email_marketing":"Email Marketing",
    "strategy":       "Стратегія",
    "copywriting":    "Копірайтинг",
    "tools":          "Інструменти",
    "paid_social":    "Paid Social",
}

CTA_LABELS = {
    "save_share":      "💾 Збережи / поділись",
    "comment_question":"💬 Питання в коментарі",
    "link_bio":        "🔗 Посилання в біо",
}

FORMAT_LABELS = {
    "carousel": "🎠 Carousel",
    "post":     "📝 Post",
    "reel":     "🎬 Reel",
}

SOURCE_BONUSES = {
    "research_scout":    3,   # знайдено скаутом — свіже і підтверджене
    "personal_experience": 2, # особистий кейс — унікально
    "trend_alert":       4,   # трендова тема — максимальний бонус
    "manual":            1,   # додано вручну
}

COLORS = {
    "green":  "\033[92m", "yellow": "\033[93m", "red": "\033[91m",
    "cyan":   "\033[96m", "purple": "\033[95m", "bold": "\033[1m",
    "reset":  "\033[0m",  "dim":    "\033[2m",  "orange": "\033[33m",
}


# ─────────────────────────────────────────────
#  УТИЛІТИ
# ─────────────────────────────────────────────

def c(text: str, *codes: str, nc: bool = False) -> str:
    if nc:
        return text
    return "".join(COLORS.get(x, "") for x in codes) + text + COLORS["reset"]


def today() -> str:
    return date.today().isoformat()


def days_since(date_str: Optional[str]) -> int:
    if not date_str:
        return 9999
    d = date.fromisoformat(date_str)
    return (date.today() - d).days


def load_db() -> dict:
    if not DB_PATH.exists():
        print(f"❌ База ідей не знайдена: {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(DB_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_db(db: dict) -> None:
    db["meta"]["last_updated"] = today()
    db["meta"]["total_ideas"] = len(db["ideas"])
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def next_id(db: dict) -> str:
    existing = [int(i["id"].split("_")[1]) for i in db["ideas"] if "_" in i["id"]]
    next_num = max(existing, default=0) + 1
    return f"idea_{next_num:03d}"


# ─────────────────────────────────────────────
#  СКОРИНГ
# ─────────────────────────────────────────────

def calculate_score(idea: dict, db: dict) -> Tuple[float, Dict[str, float]]:
    """
    Розраховує фінальний бал ідеї з урахуванням:
    - базових балів (simplicity + originality + relevance)
    - бонусу за джерело
    - штрафу за нещодавню публікацію (якщо тема вже виходила)
    - бонусу за нові / свіжі теми
    """
    scores = idea.get("scores", {})
    base = (
        scores.get("simplicity", 5) +
        scores.get("originality", 5) +
        scores.get("relevance", 5)
    )  # max 30

    # Бонус за джерело
    source_bonus = SOURCE_BONUSES.get(idea.get("source", "manual"), 1)

    # Бонус якщо тема ніколи не публікувалась
    freshness_bonus = 0
    if idea.get("publish_count", 0) == 0:
        freshness_bonus = 3
    elif days_since(idea.get("last_published")) > 60:
        freshness_bonus = 1

    # Бонус за теми з актуальних досліджень (research_scout)
    trend_bonus = 2 if idea.get("source") == "research_scout" and scores.get("relevance", 0) >= 9 else 0

    total = base + source_bonus + freshness_bonus + trend_bonus

    breakdown = {
        "base": base,
        "source_bonus": source_bonus,
        "freshness_bonus": freshness_bonus,
        "trend_bonus": trend_bonus,
        "total": total,
    }
    return total, breakdown


# ─────────────────────────────────────────────
#  ФІЛЬТР АНТИПОВТОРІВ
# ─────────────────────────────────────────────

def check_cooldowns(idea: dict, db: dict) -> Tuple[bool, List[str]]:
    """
    Перевіряє чи ідея проходить всі правила антиповтору.
    Повертає (True якщо ок, список причин блокування).
    """
    rules = db.get("rules", {})
    dir_cooldown = rules.get("direction_cooldown_days", 4)
    cta_cooldown = rules.get("cta_cooldown_days", 2)
    topic_repeat = rules.get("topic_repeat_days", 30)

    blocks = []

    # Правило 1: напрямок не частіше ніж раз в N днів
    direction = idea.get("direction", "")
    dir_last = db.get("direction_cooldowns", {}).get(direction)
    if dir_last and days_since(dir_last) < dir_cooldown:
        remaining = dir_cooldown - days_since(dir_last)
        blocks.append(f"Напрямок «{DIRECTION_LABELS.get(direction, direction)}» — ще {remaining} дн.")

    # Правило 2: CTA не частіше ніж раз в M днів
    cta = idea.get("cta", "")
    cta_last = db.get("cta_cooldowns", {}).get(cta)
    if cta_last and days_since(cta_last) < cta_cooldown:
        remaining = cta_cooldown - days_since(cta_last)
        blocks.append(f"CTA «{CTA_LABELS.get(cta, cta)}» — ще {remaining} дн.")

    # Правило 3: тема не повторюється раніше ніж через P днів
    last_pub = idea.get("last_published")
    if last_pub and days_since(last_pub) < topic_repeat:
        remaining = topic_repeat - days_since(last_pub)
        blocks.append(f"Тема публікувалась {days_since(last_pub)} дн. тому — ще {remaining} дн.")

    return len(blocks) == 0, blocks


# ─────────────────────────────────────────────
#  КОМАНДА: TOP5
# ─────────────────────────────────────────────

def cmd_top5(nc: bool = False, direction: Optional[str] = None,
             verbose: bool = False) -> None:
    db = load_db()
    rules = db.get("rules", {})
    min_score = rules.get("min_score_to_show", 50)

    candidates = []
    blocked_ideas = []

    for idea in db["ideas"]:
        if idea.get("status") in ("archived", "draft"):
            continue

        ok, reasons = check_cooldowns(idea, db)
        score, breakdown = calculate_score(idea, db)

        if direction and idea.get("direction") != direction:
            continue

        if ok:
            candidates.append((score, breakdown, idea))
        else:
            blocked_ideas.append((score, breakdown, idea, reasons))

    # Сортуємо за балом
    candidates.sort(key=lambda x: x[0], reverse=True)
    top = candidates[:rules.get("top_n", 5)]

    # ── Заголовок
    print()
    print(c("╔══════════════════════════════════════════════════════╗", "purple", nc=nc))
    print(c("║        AUTO SOURCE — ТОП-5 ТЕМ НА СЬОГОДНІ         ║", "purple", nc=nc))
    print(c("╚══════════════════════════════════════════════════════╝", "purple", nc=nc))
    print(f"\n  {c(today(), 'dim', nc=nc)}  |  Ідей у базі: {len(db['ideas'])}  |  Доступно: {len(candidates)}\n")

    if not top:
        print(c("  😕 Немає доступних тем — всі на cooldown або відфільтровані.", "yellow", nc=nc))
        print()
        return

    for rank, (score, breakdown, idea) in enumerate(top, 1):
        direction_label = DIRECTION_LABELS.get(idea["direction"], idea["direction"])
        cta_label = CTA_LABELS.get(idea["cta"], idea["cta"])
        format_label = FORMAT_LABELS.get(idea["format"], idea["format"])
        pub_count = idea.get("publish_count", 0)
        last_pub = idea.get("last_published")

        # Колір рейтингу
        rank_color = "green" if rank == 1 else "yellow" if rank <= 3 else "dim"

        print(c(f"  {'━' * 54}", "dim", nc=nc))
        print(f"  {c(f'#{rank}', rank_color, 'bold', nc=nc)}  "
              f"{c(idea['title'], 'bold', nc=nc)}")
        print(f"      {c('ID:', 'dim', nc=nc)} {idea['id']}   "
              f"{c('Бал:', 'dim', nc=nc)} {c(str(score), 'green', 'bold', nc=nc)}/43   "
              f"{c('Публ.:', 'dim', nc=nc)} {'ніколи' if pub_count == 0 else f'{pub_count}x'}")
        print()
        print(f"      {c('📐 Кут:', 'cyan', nc=nc)} {idea['angle']}")
        print()
        print(f"      {c('🗂', 'dim', nc=nc)} {direction_label}   "
              f"{c('📱', 'dim', nc=nc)} {format_label}   "
              f"{c('🎯', 'dim', nc=nc)} {cta_label}")

        if idea.get("source_url"):
            print(f"      {c('🔗', 'dim', nc=nc)} {idea['source_url']}")

        if verbose:
            print(f"\n      {c('Скоринг:', 'dim', nc=nc)} "
                  f"simplicity={idea['scores']['simplicity']} "
                  f"originality={idea['scores']['originality']} "
                  f"relevance={idea['scores']['relevance']} "
                  f"| +{breakdown['source_bonus']} (джерело) "
                  f"+{breakdown['freshness_bonus']} (свіжість) "
                  f"+{breakdown['trend_bonus']} (тренд)")

        tags = " ".join(f"#{t}" for t in idea.get("tags", []))
        if tags:
            print(f"      {c(tags, 'dim', nc=nc)}")
        print()

    print(c(f"  {'━' * 54}", "dim", nc=nc))
    print()
    print(c("  💡 Після публікації:", "cyan", nc=nc))
    print(f"     python3 auto_source.py publish --id <idea_id>")
    print()

    # Показуємо скільки заблоковано
    if blocked_ideas:
        print(c(f"  ⏳ Заблоковано cooldown: {len(blocked_ideas)} тем", "dim", nc=nc))
        if verbose:
            for score, _, idea, reasons in blocked_ideas[:3]:
                print(f"     • {idea['title'][:50]}… — {reasons[0]}")
        print()


# ─────────────────────────────────────────────
#  КОМАНДА: PUBLISH
# ─────────────────────────────────────────────

def cmd_publish(idea_id: str, platform: str = "instagram",
                nc: bool = False) -> None:
    db = load_db()

    idea = next((i for i in db["ideas"] if i["id"] == idea_id), None)
    if not idea:
        print(c(f"❌ Ідея не знайдена: {idea_id}", "red", nc=nc), file=sys.stderr)
        sys.exit(1)

    # Оновлюємо ідею
    idea["last_published"] = today()
    idea["publish_count"] = idea.get("publish_count", 0) + 1

    # Оновлюємо cooldown напрямку і CTA
    db.setdefault("direction_cooldowns", {})[idea["direction"]] = today()
    db.setdefault("cta_cooldowns", {})[idea["cta"]] = today()

    # Додаємо в лог публікацій
    log_entry = {
        "date": today(),
        "idea_id": idea_id,
        "title": idea["title"],
        "direction": idea["direction"],
        "format": idea["format"],
        "cta": idea["cta"],
        "platform": platform,
    }
    db.setdefault("publish_log", []).append(log_entry)

    save_db(db)
    update_report(db)

    print()
    print(c("  ✅ Публікацію зафіксовано!", "green", "bold", nc=nc))
    print(f"     Тема:     {idea['title']}")
    print(f"     Дата:     {today()}")
    print(f"     Платформа: {platform}")
    print(f"     Напрямок: {DIRECTION_LABELS.get(idea['direction'], idea['direction'])} — cooldown {db['rules']['direction_cooldown_days']} дн.")
    print(f"     CTA:      {CTA_LABELS.get(idea['cta'], idea['cta'])} — cooldown {db['rules']['cta_cooldown_days']} дн.")
    print()
    print(c("  📊 Звіт оновлено → publish_report.md", "cyan", nc=nc))
    print()


# ─────────────────────────────────────────────
#  КОМАНДА: ADD
# ─────────────────────────────────────────────

def cmd_add(title: str, angle: str, direction: str, cta: str,
            fmt: str, source: str, source_url: Optional[str],
            tags: List[str], simplicity: int, originality: int,
            relevance: int, nc: bool = False) -> None:
    db = load_db()

    new_id = next_id(db)
    idea = {
        "id": new_id,
        "title": title,
        "angle": angle,
        "direction": direction,
        "cta": cta,
        "format": fmt,
        "source": source,
        "source_url": source_url,
        "tags": tags,
        "scores": {
            "simplicity": simplicity,
            "originality": originality,
            "relevance": relevance,
        },
        "total_score": 0,
        "last_published": None,
        "publish_count": 0,
        "status": "ready",
    }

    db["ideas"].append(idea)
    save_db(db)

    score, _ = calculate_score(idea, db)
    print()
    print(c(f"  ✅ Додано ідею {new_id}", "green", "bold", nc=nc))
    print(f"     Назва: {title}")
    print(f"     Бал:   {score}/43")
    print()


# ─────────────────────────────────────────────
#  КОМАНДА: LOG
# ─────────────────────────────────────────────

def cmd_log(last_n: int = 10, nc: bool = False) -> None:
    db = load_db()
    log = db.get("publish_log", [])

    print()
    print(c("  📋 ЖУРНАЛ ПУБЛІКАЦІЙ", "cyan", "bold", nc=nc))
    print(c("  " + "─" * 54, "dim", nc=nc))
    print()

    if not log:
        print(c("  Поки порожньо — публікацій не було.", "dim", nc=nc))
        print()
        return

    for entry in reversed(log[-last_n:]):
        dir_label = DIRECTION_LABELS.get(entry.get("direction", ""), entry.get("direction", ""))
        fmt_label = FORMAT_LABELS.get(entry.get("format", ""), "")
        print(f"  {c(entry['date'], 'yellow', nc=nc)}  {c(entry['idea_id'], 'dim', nc=nc)}")
        print(f"     {entry['title']}")
        print(f"     {dir_label} | {fmt_label} | {entry.get('platform', '—')}")
        print()


# ─────────────────────────────────────────────
#  КОМАНДА: STATS
# ─────────────────────────────────────────────

def cmd_stats(nc: bool = False) -> None:
    db = load_db()
    ideas = db["ideas"]
    log = db.get("publish_log", [])

    print()
    print(c("  📊 СТАТИСТИКА БАЗИ ІДЕЙ", "cyan", "bold", nc=nc))
    print(c("  " + "─" * 54, "dim", nc=nc))
    print()

    # По напрямках
    dir_counts: Dict[str, Dict] = {}
    for idea in ideas:
        d = idea["direction"]
        if d not in dir_counts:
            dir_counts[d] = {"total": 0, "published": 0, "on_cooldown": False}
        dir_counts[d]["total"] += 1
        if idea.get("publish_count", 0) > 0:
            dir_counts[d]["published"] += 1

    # Cooldown статуси
    for d, last in db.get("direction_cooldowns", {}).items():
        if d in dir_counts and days_since(last) < db["rules"]["direction_cooldown_days"]:
            dir_counts[d]["on_cooldown"] = True

    print(c("  НАПРЯМКИ:", "bold", nc=nc))
    for d, info in sorted(dir_counts.items(), key=lambda x: -x[1]["total"]):
        label = DIRECTION_LABELS.get(d, d)
        cd_mark = c(" ⏳", "yellow", nc=nc) if info["on_cooldown"] else c(" ✅", "green", nc=nc)
        bar = "█" * info["published"] + "░" * (info["total"] - info["published"])
        print(f"    {label:<22} {bar:<10} {info['published']}/{info['total']} опубл.{cd_mark}")

    print()

    # По CTA
    cta_pub: Dict[str, int] = {}
    for entry in log:
        cta = entry.get("cta", "unknown")
        cta_pub[cta] = cta_pub.get(cta, 0) + 1

    print(c("  CTA (по частоті використання):", "bold", nc=nc))
    for cta, label in CTA_LABELS.items():
        count = cta_pub.get(cta, 0)
        last = db.get("cta_cooldowns", {}).get(cta)
        cd_str = ""
        if last and days_since(last) < db["rules"]["cta_cooldown_days"]:
            cd_str = c(f" ⏳ +{db['rules']['cta_cooldown_days'] - days_since(last)}дн", "yellow", nc=nc)
        print(f"    {label:<30} {count}x{cd_str}")

    print()

    # Топ ідей за балом
    print(c("  ТОП-5 ІДЕЙ ЗА СКОРОМ:", "bold", nc=nc))
    scored = [(calculate_score(i, db)[0], idx, i) for idx, i in enumerate(ideas) if i.get("status") != "archived"]
    scored.sort(key=lambda x: x[0], reverse=True)
    for score, _, idea in scored[:5]:
        print(f"    {c(str(score), 'green', 'bold', nc=nc)}/43  {idea['title'][:55]}")

    print()
    print(f"  Всього ідей: {len(ideas)} | Опубліковано: {len(log)} разів")
    print()


# ─────────────────────────────────────────────
#  КОМАНДА: REPLENISH (поповнення з research)
# ─────────────────────────────────────────────

def cmd_replenish(learnings_path: Optional[str] = None, nc: bool = False) -> None:
    """
    Зчитує new_learnings.md, парсить записи ⭐4-5,
    і пропонує додати їх у базу ідей як нові теми.
    """
    if not learnings_path:
        learnings_path = str(Path(__file__).parent.parent / "research" / "new_learnings.md")

    if not Path(learnings_path).exists():
        print(c(f"❌ Файл не знайдено: {learnings_path}", "red", nc=nc))
        return

    db = load_db()
    existing_urls = {i.get("source_url") for i in db["ideas"] if i.get("source_url")}

    with open(learnings_path, encoding="utf-8") as f:
        content = f.read()

    import re
    # Парсимо рядки таблиці | Дата | Джерело | URL | Суть | ⭐4 або ⭐5 |
    rows = re.findall(
        r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+)\s*\|\s*(https?://[^\s|]+)\s*\|\s*([^|]+)\s*\|\s*⭐([45])\s*\|",
        content
    )

    new_count = 0
    print()
    print(c("  🔄 ПОПОВНЕННЯ БАЗИ З RESEARCH SCOUT", "cyan", "bold", nc=nc))
    print(c("  " + "─" * 54, "dim", nc=nc))
    print()

    for pub_date, source, url, insight, star in rows:
        url = url.strip()
        if url in existing_urls:
            continue

        insight = insight.strip()
        star_int = int(star)

        # Автоматично визначаємо напрямок за ключовими словами
        insight_lower = insight.lower()
        if "meta" in insight_lower or "facebook" in insight_lower:
            direction = "meta_ads"
        elif "tiktok" in insight_lower:
            direction = "tiktok_ads"
        elif "email" in insight_lower:
            direction = "email_marketing"
        elif "real estate" in insight_lower or "нерухом" in insight_lower:
            direction = "real_estate"
        else:
            direction = "strategy"

        new_id = next_id(db)

        idea = {
            "id": new_id,
            "title": f"[Scout {pub_date}] {insight[:70]}",
            "angle": insight,
            "direction": direction,
            "cta": random.choice(["save_share", "comment_question"]),
            "format": "post",
            "source": "research_scout",
            "source_url": url,
            "tags": ["scout", "research", str(pub_date[:7])],
            "scores": {
                "simplicity": 7,
                "originality": star_int + 4,  # 8 або 9
                "relevance": star_int + 4,
            },
            "total_score": 0,
            "last_published": None,
            "publish_count": 0,
            "status": "ready",
        }

        db["ideas"].append(idea)
        existing_urls.add(url)
        new_count += 1

        print(f"  ✅ {new_id}: {insight[:60]}…")
        print(f"     Джерело: {source.strip()} ⭐{star} | Напрямок: {DIRECTION_LABELS.get(direction, direction)}")
        print()

    if new_count == 0:
        print(c("  ℹ️  Нових записів не знайдено (всі вже є в базі).", "dim", nc=nc))
    else:
        save_db(db)
        print(c(f"  📥 Додано {new_count} нових ідей у базу.", "green", "bold", nc=nc))
    print()


# ─────────────────────────────────────────────
#  ЗВІТ ПУБЛІКАЦІЙ
# ─────────────────────────────────────────────

def update_report(db: dict) -> None:
    """Оновлює publish_report.md після кожної публікації."""
    log = db.get("publish_log", [])
    ideas_map = {i["id"]: i for i in db["ideas"]}

    lines = [
        "# 📊 Звіт Публікацій — Auto Source",
        f"_Оновлено: {today()} | Всього публікацій: {len(log)}_",
        "",
        "---",
        "",
        "## 📅 Останні публікації",
        "",
        "| Дата | ID | Тема | Напрямок | Формат | Платформа |",
        "|------|----|------|---------|--------|-----------|",
    ]

    for entry in reversed(log[-20:]):
        dir_label = DIRECTION_LABELS.get(entry.get("direction", ""), "—")
        fmt_label = entry.get("format", "—")
        lines.append(
            f"| {entry['date']} | {entry['idea_id']} | "
            f"{entry['title'][:45]}… | {dir_label} | {fmt_label} | {entry.get('platform', '—')} |"
        )

    # Cooldown статуси
    lines += [
        "",
        "---",
        "",
        "## ⏳ Поточні Cooldowns",
        "",
        "| Тип | Останнє | Відкриється |",
        "|-----|---------|------------|",
    ]

    rules = db.get("rules", {})
    for direction, last_date in db.get("direction_cooldowns", {}).items():
        days = days_since(last_date)
        cooldown = rules.get("direction_cooldown_days", 4)
        if days < cooldown:
            opens = (date.fromisoformat(last_date) + timedelta(days=cooldown)).isoformat()
            label = DIRECTION_LABELS.get(direction, direction)
            lines.append(f"| 🗂 {label} | {last_date} | {opens} |")

    for cta, last_date in db.get("cta_cooldowns", {}).items():
        days = days_since(last_date)
        cooldown = rules.get("cta_cooldown_days", 2)
        if days < cooldown:
            opens = (date.fromisoformat(last_date) + timedelta(days=cooldown)).isoformat()
            label = CTA_LABELS.get(cta, cta)
            lines.append(f"| 🎯 {label} | {last_date} | {opens} |")

    # Статистика по напрямках
    dir_counts: Dict[str, int] = {}
    for entry in log:
        d = entry.get("direction", "unknown")
        dir_counts[d] = dir_counts.get(d, 0) + 1

    lines += [
        "",
        "---",
        "",
        "## 📈 Статистика по напрямках",
        "",
        "| Напрямок | Кількість |",
        "|----------|-----------|",
    ]
    for d, cnt in sorted(dir_counts.items(), key=lambda x: -x[1]):
        label = DIRECTION_LABELS.get(d, d)
        lines.append(f"| {label} | {cnt} |")

    lines += ["", f"---", f"_База ідей: {len(db['ideas'])} тем_"]

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="auto_source.py — розумний підбір тем з бази ідей",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
КОМАНДИ:
  top5      — вивести топ-5 тем для роботи сьогодні
  publish   — позначити тему як опубліковану
  add       — додати нову ідею в базу
  log       — журнал публікацій
  stats     — статистика бази
  replenish — поповнити базу з research/new_learnings.md

ПРИКЛАДИ:
  python3 auto_source.py top5
  python3 auto_source.py top5 --direction meta_ads
  python3 auto_source.py top5 --verbose
  python3 auto_source.py publish --id idea_001 --platform instagram
  python3 auto_source.py log --last 5
  python3 auto_source.py stats
  python3 auto_source.py replenish
  python3 auto_source.py add \\
      --title "Нова ідея" \\
      --angle "Кут зору" \\
      --direction meta_ads \\
      --cta save_share \\
      --format carousel \\
      --source personal_experience \\
      --simplicity 8 --originality 9 --relevance 8
        """,
    )
    parser.add_argument("command",
                        choices=["top5", "publish", "add", "log", "stats", "replenish"],
                        help="Команда")
    parser.add_argument("--id", help="ID ідеї (для publish)")
    parser.add_argument("--platform", default="instagram",
                        help="Платформа публікації (instagram/tiktok/facebook/telegram)")
    parser.add_argument("--direction", help="Фільтр по напрямку (для top5)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Детальний вивід")
    parser.add_argument("--no-color", action="store_true", help="Без кольорів")
    parser.add_argument("--last", type=int, default=10,
                        help="Кількість записів для log (за замовчуванням: 10)")
    # Параметри для add
    parser.add_argument("--title")
    parser.add_argument("--angle")
    parser.add_argument("--cta", choices=["save_share", "comment_question", "link_bio"])
    parser.add_argument("--format", dest="fmt",
                        choices=["carousel", "post", "reel"])
    parser.add_argument("--source",
                        choices=["research_scout", "personal_experience", "trend_alert", "manual"],
                        default="manual")
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--tags", nargs="*", default=[])
    parser.add_argument("--simplicity", type=int, default=7)
    parser.add_argument("--originality", type=int, default=7)
    parser.add_argument("--relevance", type=int, default=7)
    parser.add_argument("--learnings", default=None,
                        help="Шлях до new_learnings.md (для replenish)")

    args = parser.parse_args()
    nc = args.no_color

    if args.command == "top5":
        cmd_top5(nc=nc, direction=args.direction, verbose=args.verbose)

    elif args.command == "publish":
        if not args.id:
            print("❌ Вкажи --id ідеї", file=sys.stderr)
            sys.exit(2)
        cmd_publish(args.id, platform=args.platform, nc=nc)

    elif args.command == "add":
        for req in ["title", "angle", "direction", "cta", "fmt"]:
            if not getattr(args, req):
                print(f"❌ Потрібен параметр --{req.replace('_', '-')}", file=sys.stderr)
                sys.exit(2)
        cmd_add(
            title=args.title, angle=args.angle, direction=args.direction,
            cta=args.cta, fmt=args.fmt, source=args.source,
            source_url=args.source_url, tags=args.tags,
            simplicity=args.simplicity, originality=args.originality,
            relevance=args.relevance, nc=nc,
        )

    elif args.command == "log":
        cmd_log(last_n=args.last, nc=nc)

    elif args.command == "stats":
        cmd_stats(nc=nc)

    elif args.command == "replenish":
        cmd_replenish(learnings_path=args.learnings, nc=nc)


if __name__ == "__main__":
    main()
