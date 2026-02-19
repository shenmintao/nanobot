---
description: How to use SillyTavern features in docker-compose
---

You can access the `nanobot st` CLI commands using `docker compose`. Data updates are automatically persisted to your host machine's `~/.nanobot` directory because of the volume mapping in `docker-compose.yml`.

### 1. Run commands using a temporary container

Use `docker compose run --rm` to execute one-off commands. This is useful for importing files or checking status.

```bash
# Check status
docker compose run --rm nanobot-cli st status

# List characters
docker compose run --rm nanobot-cli st char list

# Import a character (file must be available inside the container)
# Tip: Put your files in ~/.nanobot so they are mounted to /root/.nanobot
docker compose run --rm nanobot-cli st char import /root/.nanobot/Alice.json
```

### 2. Run commands in a running container

If you have `nanobot-gateway` running, you can execute commands inside it:

```bash
docker compose exec nanobot-gateway nanobot st status
```

### 3. Data Persistence

Your data is safe! The `docker-compose.yml` mounts:
`- ~/.nanobot:/root/.nanobot`

This means:
- Characters are stored in `~/.nanobot/sillytavern/characters/` (Host)
- World Info is stored in `~/.nanobot/sillytavern/world_info/` (Host)
- Presets are stored in `~/.nanobot/sillytavern/presets/` (Host)

You can manage these files directly on your host machine if needed.
