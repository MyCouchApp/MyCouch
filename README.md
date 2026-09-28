# 🛋️ MyCouch

**Your media. Your history. What's next?**

MyCouch is a self-hosted companion for exploring and understanding a Plex media library. It combines library analysis, viewing activity, discovery/search, personal play history, cleanup review, Radarr/Sonarr matching, Tautulli activity and optional Discord integration.

> MyCouch is an independent project and is not affiliated with Plex, Tautulli, Radarr, Sonarr, Discord, Emby or Jellyfin.

## Current release — v2.9.8

v2.9.8 focuses on making MyCouch easier to navigate and easier for new users to understand, while keeping the existing Plex, Tautulli, Radarr, Sonarr and Discord functionality intact.

### What's new in v2.9.8

- Reorganised the main navigation to put the most-used MyCouch features first.
- Renamed **Cleanup** to **Server Stats** to better reflect the information available on the page.
- Added a collapsible **What is MyCouch?** introduction to the Dashboard.
- Added direct links from the Dashboard introduction to **My History**, **Smart Search**, **Movies**, **TV**, **Server Stats** and Discord information.
- The Dashboard remembers whether the **What is MyCouch?** introduction has been expanded or collapsed.
- Added a collapsible **Smart Search on Discord** guide explaining how to use the `/search` command.
- Refined navigation wording and general UI copy.

### MyCouch features

- **What's Playing on MyCouch?** live activity on the dashboard.
- Movies and TV tables with natural/numeric sortable columns.
- Played Count and popularity filters for 7/30/90 days, one year and all time.
- Plex browser/PIN sign-in for private **My History** viewing stats.
- **Smart Search** with Plex posters and Open in Plex links.
- **Server Stats**, protected titles, Review Queue and Leaving Soon.
- Read-only Radarr/Sonarr matching.
- Tautulli-backed aggregate activity and personal history.
- Discord webhooks plus optional `/search` bot integration.
- Dark/light theme — light mode remains available by special request from Kyle, who apparently prefers staring into the sun.

### Earlier fixes included

- **v2.9.6.1:** fixed the SQLite `NATURAL` collation syntax error.
- **v2.9.6.2:** fixed natural sorting for Unicode numeric characters such as superscript `²`.

## Fresh install on Windows

1. Install Python 3.
2. Extract MyCouch to a folder of your choice.
3. Run `start.ps1`.
4. Open `http://localhost:8090`.
5. Create the first admin account.
6. In **Settings**, select your Plex SQLite database and build the library cache.
7. Configure Tautulli, Radarr, Sonarr, Plex and Discord only if you want those integrations.

`start.ps1` creates a local `.venv` and installs the packages in `requirements.txt`.

You can optionally set `PLEX_DB` before launch instead of selecting the database in Settings. See `.env.example` for an example; MyCouch does not automatically load `.env` files.

## Upgrade from LibraryLens

Stop LibraryLens first and make a backup of its folder.

Copy these existing runtime files into the new MyCouch folder:

- `auditor.db`
- `auditor-cache.db`
- `.pla-secret`

Keeping `.pla-secret` preserves existing remembered admin sessions. The legacy filenames are intentionally retained for compatibility.

Then run `start.ps1`. Your settings, protected titles, review queue, Tautulli cache, Arr matches, Discord settings and other local state remain in the existing databases.

## Security / privacy

Do **not** commit or publish your runtime databases or secret file. The supplied `.gitignore` excludes:

- `auditor.db` and SQLite sidecars
- `auditor-cache.db` and SQLite sidecars
- `.pla-secret`
- Plex snapshot files
- backups/logs
- `.env` files
- Python virtual environments and caches

API keys, Plex server tokens, Discord bot tokens/webhooks and private viewing identities are stored locally. Public pages expose aggregate activity rather than viewer identities.

Do not port-forward the Flask development server on port 8090 directly to the Internet. Use an HTTPS reverse proxy or secure tunnel if remote access is required.

## Plex sign-in

MyCouch uses Plex's browser/PIN authorization flow and never asks for a Plex password. The user sign-in token used to identify the account is not persisted as the user's login credential. Server-side Plex integration credentials configured by an administrator remain local.

## Discord

Outgoing webhooks can publish aggregate statistics, recommendations and Leaving Soon notices. The optional bot adds `/search`, returning MyCouch movie matches with posters and Open in Plex links. Bot tokens and webhook URLs must be entered locally and should never be committed to Git.

## GitHub

The intended project home is the **MyCouchApp** organisation with the **MyCouch** repository.

Before any public push, verify the staged files with `git status` and confirm that no databases, tokens, webhooks, backups, logs or personal media paths are included.
