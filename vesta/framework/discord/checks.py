from cashews import cache


@cache(
    ttl="3h",
    key="blacklist:{object_id}:{object_type}",
)
async def is_blacklisted(
    bot, object_id: int, object_type: str
) -> bool:
    if object_type == "user":
        query = "SELECT 1 FROM blacklist WHERE user_id = $1"
    elif object_type == "guild":
        query = "SELECT 1 FROM guildblacklist WHERE guild_id = $1"
    else:
        query = "SELECT 1 FROM blacklists WHERE object_id = $1 AND object_type = $2"
        return bool(
            await bot.pool.fetchval(
                query, object_id, object_type
            )
        )

    return bool(await bot.pool.fetchval(query, object_id))


def invalidate_blacklist_cache(
    object_id: int, object_type: str
):
    is_blacklisted.invalidate(
        f"blacklist:{object_id}:{object_type}"
    )
