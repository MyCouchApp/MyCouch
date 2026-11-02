# MyCouch on Docker

MyCouch can run on the Docker laptop with its application state persisted in `./data`.

## Important: Plex database access

MyCouch still needs read access to the Plex SQLite library database when you run **Update Plex Now**. The container cannot use the old Windows `C:\...` database path.

Expose or copy the Plex database folder to the Docker laptop, then mount it read-only into the container. For example:

```yaml
volumes:
  - ./data:/app/data
  - /mnt/plex-db:/plex-db:ro
environment:
  PLEX_DB: /plex-db/com.plexapp.plugins.library.db
```

Use the actual mounted path and Plex database filename on your system.

## First test

```sh
mkdir -p /srv/mycouch
cd /srv/mycouch
# extract/copy the MyCouch release here
mkdir -p data
docker compose up -d --build
docker compose logs -f mycouch
```

Open `http://192.168.1.200:8090`.

## Migrating your existing MyCouch state

Stop the Windows MyCouch instance first, then copy these files from the existing MyCouch folder into `/srv/mycouch/data/`:

- `auditor.db`
- `auditor-cache.db`
- `.pla-secret`

Keeping `.pla-secret` preserves the Flask/session signing secret. The SQLite databases retain your MyCouch configuration, cache, settings, integrations, playlists, security activity, Kuma settings, etc.

After copying them:

```sh
cd /srv/mycouch
docker compose up -d --build
docker compose logs -f mycouch
```

## URLs after migration

Because MyCouch is then running on the Docker laptop, local service integrations should use addresses reachable from the container. Do not use `localhost` for Plex, Tautulli, Radarr or Sonarr unless that service is inside the same container.

For this environment the expected addresses include:

- Plex: `http://192.168.1.10:32400`
- Tautulli: `http://192.168.1.200:8181`
- Uptime Kuma: `http://192.168.1.200:3001`
- Radarr: `http://192.168.1.10:7878`
- Sonarr: `http://192.168.1.10:7879`

Your Cloudflare Tunnel can then be changed from the Windows MyCouch origin to `http://192.168.1.200:8090` after the Docker copy is confirmed working.
