# MyCouch on Docker

MyCouch runs in Docker using the Waitress production server.

Application data is stored in `./data`, preserving configuration, sessions and the library cache across container replacements.

## Requirements

- Docker Engine and Docker Compose
- Access to a Plex library database or completed Plex database backups
- A persistent directory for MyCouch application data

## Quick start

```sh
git clone https://github.com/MyCouchApp/MyCouch.git
cd MyCouch
mkdir -p data
docker compose up -d --build
```

Open `http://localhost:8090`.

The default Compose file starts MyCouch but does not mount a Plex database. Configure one of the options below before refreshing the library.

## Recommended: Automatic Plex backup discovery

Mount a directory containing completed Plex database backups read-only.

Create `docker-compose.override.yml`:

```yaml
services:
  mycouch:
    environment:
      PLEX_BACKUP_DIR: /plex-backups
    volumes:
      - "/path/to/your/PlexBackup:/plex-backups:ro"
```

Replace `/path/to/your/PlexBackup` with the actual directory on your Docker host.

MyCouch recognises dated Plex library backups such as:

```text
com.plexapp.plugins.library.db-2026-11-16
```

It selects the newest valid backup, ignoring Plex blobs databases and incomplete or unsuitable candidates.

The backup directory must already be mounted and accessible on the Docker host. MyCouch does not mount NAS shares automatically.

### Automatic refresh

In Admin Settings, enable Plex automatic updates and select:

- Every 6 hours
- Every 12 hours
- Daily

Scheduled checks refresh the local library cache only when the selected backup differs from the cached source.

**Update Plex Now** forces a manual refresh.

The Admin page displays the backup currently in use, the last successful cache refresh and the latest backup status.

If the NAS becomes unavailable or a refresh fails, the existing completed cache remains intact.

## Alternative: Read-only Plex database

If you are not using dated NAS backups, mount a Plex database directory instead:

```yaml
services:
  mycouch:
    environment:
      PLEX_DB: /plex-db/com.plexapp.plugins.library.db
      PLEX_BACKUP_DIR: ""
    volumes:
      - "/path/to/plex/database:/plex-db:ro"
```

Replace the host path with the actual Plex database directory.

MyCouch uses a temporary SQLite snapshot when rebuilding the cache. It does not write changes to the source database.

In this mode, scheduled refreshes do not use NAS backup change detection.

## Local Docker configuration

Keep machine-specific paths, port mappings and environment settings in `docker-compose.override.yml`.

This file is excluded from Git.

For example, to publish MyCouch on host port 8088 instead of 8090:

```yaml
services:
  mycouch:
    ports: !override
      - "8088:8090"
```

The `!override` directive requires Docker Compose 2.24.4 or newer.

Check the merged configuration before deployment:

```sh
docker compose config
```

## Migrating existing MyCouch data

Stop the previous MyCouch instance before copying its application state.

Copy the following files into the new installation's `data/` directory:

- `auditor.db`
- `auditor-cache.db`
- `.pla-secret`

Preserving the existing secret maintains compatibility with previously signed sessions.

The databases retain MyCouch configuration and cached information.

## Updating MyCouch

```sh
git pull
docker compose up -d --build
docker compose ps
```

## Troubleshooting

Check container health and logs:

```sh
docker compose ps
docker compose logs --tail=100 mycouch
```

Verify the backup directory is visible inside the container:

```sh
docker compose exec mycouch ls -lh /plex-backups
```

For installations using a manually mounted Plex database, check `/plex-db` instead.

The source database and NAS backups should always be mounted read-only.
