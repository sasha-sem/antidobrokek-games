from __future__ import annotations

import uuid

from test_game import seed_pack

from app.services.game import GameService
from app.services.stats import StatsService


async def test_stats_and_csv_sorting(settings, database, storage) -> None:
    pack_id = await seed_pack(database, storage)
    game = GameService(database.session_factory, settings, storage)
    room, _ = await game.create_room(pack_id, 5)
    player, _ = await game.join(room.code, "Игрок", str(uuid.uuid4()))
    await game.set_connection(player.id, True)
    await game.set_player_ready(room.id, player.id)
    await game.preload(room.id, first=True)
    await game.start_question(room.id)
    await game.submit_answer(room.id, player.id, "sasha")
    await game.reveal(room.id, automatic=True)
    await game.set_reaction(room.id, player.id, 1)

    stats = StatsService(database.session_factory)
    rows = await stats.rows()
    assert rows[0]["telegram_message_id"] == 1
    assert rows[0]["approval_percent"] == 100
    assert rows[0]["guess_accuracy_percent"] == 100
    csv = stats.csv(rows)
    assert "telegram_chat_id,telegram_message_id" in csv
    assert "-100,1,sasha,Саша" in csv
