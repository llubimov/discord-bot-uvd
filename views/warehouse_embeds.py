import discord
from views.warehouse_theme import BLUE


def build_cart_embed(items: list, *, is_request: bool = True) -> discord.Embed:
    if not items:
        embed = discord.Embed(
            title="📦 Запрос снаряжения",
            description=(
                "Корзина пуста.\n"
                "Нажми **«ДОБАВИТЬ ЕЩЕ»** — выбери категорию и предметы, затем **«ОТПРАВИТЬ»**."
            ),
            color=BLUE,
        )
        embed.set_footer(text="Быстрые комплекты: ГРОМ или общий (средние/тяжёлые)")
        return embed

    title = "🛒 Твоя корзина" if not is_request else "📦 Запрос на склад"
    embed = discord.Embed(
        title=title,
        description="Текущий состав заявки",
        color=BLUE,
    )

    by_category: dict[str, list[dict]] = {}
    for item in items:
        cat = item["category"]
        by_category.setdefault(cat, []).append(item)

    weapon_count = 0
    armor_count = 0
    meds_count = 0

    for cat, cat_items in by_category.items():
        cat_text = ""
        for it in cat_items:
            qty = int(it.get("quantity", 0))
            cat_text += f"• {it['item']} — **{qty}** шт\n"
            cat_norm = str(cat).lower()
            if "оруж" in cat_norm:
                weapon_count += qty
            elif "брон" in cat_norm:
                armor_count += qty
            elif "мед" in cat_norm:
                meds_count += qty
        embed.add_field(name=cat, value=cat_text.rstrip(), inline=False)

    stats = []
    if weapon_count > 0:
        stats.append(f"🔫 Оружие: {weapon_count}/3")
    if armor_count > 0:
        stats.append(f"🛡️ Броня: {armor_count}/20")
    if meds_count > 0:
        stats.append(f"💊 Медицина: {meds_count}/20")
    if stats:
        embed.add_field(name="📊 Лимиты", value=" · ".join(stats), inline=False)

    embed.set_footer(text=f"Позиций в заявке: {len(items)}")
    return embed
