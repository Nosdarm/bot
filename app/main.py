from fastapi import FastAPI

app = FastAPI(title="Text RPG Bot Backend")

@app.get("/")
async def read_root():
    return {"message": "Text RPG Bot Backend is running!"}

# Placeholder for bot token (replace with environment variable or config file later)
BOT_TOKEN = "YOUR_DISCORD_BOT_TOKEN"

if __name__ == "__main__":
    # This part is for local debugging if needed,
    # but Uvicorn will be used for actual deployment.
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
