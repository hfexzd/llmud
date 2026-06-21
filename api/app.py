"""FastAPI application factory — wires all subsystems together."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from dm.client import LLMClient
from db.repository import PlayerRepository, NPCRepository, WorldRepository
from engine.models import DEFAULT_PLAYER, DEFAULT_ENCOUNTER, ALL_NPC_PROFILES
from engine.world import WorldEngine
from api.routes import create_router
from api.deps import get_llm_client, create_db_connection_from_env


def seed_database(player_repo: PlayerRepository, npc_repo: NPCRepository):
    """Seed the database with default player and NPC data."""
    if player_repo.get(DEFAULT_PLAYER.id) is None:
        player_repo.save(DEFAULT_PLAYER)

    for profile in ALL_NPC_PROFILES:
        if npc_repo.get_profile(profile.id) is None:
            npc_repo.save_profile(
                npc_id=profile.id,
                name=profile.name,
                persona=profile.persona,
                secret=profile.secret,
                motive=profile.motive,
                default_scene=profile.default_scene,
                favorability=profile.favorability,
                relationship_stage=profile.relationship_stage,
            )
            npc_repo.save_memory(profile.id)


def create_app(llm_client: LLMClient | None = None, db_path: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    llm = llm_client or get_llm_client()
    conn = create_db_connection_from_env(db_path)
    player_repo = PlayerRepository(conn)
    npc_repo = NPCRepository(conn)
    world_repo = WorldRepository(conn)

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
    world_engine = WorldEngine()
    router = create_router(
        llm_client=llm,
        player_repo=player_repo,
        npc_repo=npc_repo,
        encounter=DEFAULT_ENCOUNTER,
        world_engine=world_engine,
        world_repo=world_repo,
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