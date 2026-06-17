"""修仙 MUD — llmud entry point."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("api.app:create_app", host="0.0.0.0", port=8001, factory=True)