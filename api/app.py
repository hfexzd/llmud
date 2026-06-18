"""FastAPI application factory — wires all subsystems together."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from dm.client import LLMClient
from db.repository import PlayerRepository, NPCRepository
from engine.models import DEFAULT_PLAYER, DEFAULT_ENCOUNTER
from npc.models import DEFAULT_NPC_PROFILE
from api.routes import create_router
from api.deps import get_llm_client, create_db_connection_from_env


def seed_database(player_repo: PlayerRepository, npc_repo: NPCRepository):
    """Seed the database with default player and NPC data."""
    if player_repo.get(DEFAULT_PLAYER.id) is None:
        player_repo.save(DEFAULT_PLAYER)

    if npc_repo.get_profile(DEFAULT_NPC_PROFILE.id) is None:
        npc_repo.save_profile(
            npc_id=DEFAULT_NPC_PROFILE.id,
            name=DEFAULT_NPC_PROFILE.name,
            persona=DEFAULT_NPC_PROFILE.persona,
            secret=DEFAULT_NPC_PROFILE.secret,
            motive=DEFAULT_NPC_PROFILE.motive,
            default_scene=DEFAULT_NPC_PROFILE.default_scene,
            favorability=DEFAULT_NPC_PROFILE.favorability,
            relationship_stage=DEFAULT_NPC_PROFILE.relationship_stage,
        )
        npc_repo.save_memory(DEFAULT_NPC_PROFILE.id)


def create_app(llm_client: LLMClient | None = None, db_path: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    llm = llm_client or get_llm_client()
    conn = create_db_connection_from_env(db_path)
    player_repo = PlayerRepository(conn)
    npc_repo = NPCRepository(conn)

    # Seed default data
    seed_database(player_repo, npc_repo)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        conn.close()

    app = FastAPI(title="修仙 MUD — llmud", lifespan=lifespan)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include game routes
    router = create_router(
        llm_client=llm,
        player_repo=player_repo,
        npc_repo=npc_repo,
        encounter=DEFAULT_ENCOUNTER,
    )
    app.include_router(router)

    # Serve static frontend (if available)
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    if os.path.isdir(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    # Store deps on app state for testing
    app.state.llm_client = llm
    app.state.db_conn = conn
    app.state.player_repo = player_repo
    app.state.npc_repo = npc_repo

    return app