# 🛋️ MyCouch

**A self-hosted Plex dashboard for exploring your media library, viewing history, server stats and finding what to watch next.**

**Your media. Your history. What's next?**

MyCouch is a free, open-source companion for Plex Media Server. It brings Plex library statistics, personal viewing history, live activity, natural-language Smart Search and media discovery into one simple web dashboard.

MyCouch integrates with Plex, Tautulli, Radarr and Sonarr, with optional Discord integration for searching your Plex library using the `/search` command.

> MyCouch is an independent project and is not affiliated with Plex, Tautulli, Radarr, Sonarr, Discord, Emby or Jellyfin.

## Features

* Plex dashboard and library statistics
* Personal Plex viewing history with Plex sign-in
* Live **What's Playing on MyCouch?** activity
* Natural-language Smart Search
* Recently Added and Recently Watched
* Movie and TV library analysis
* Server and library size statistics
* Played Count and popularity filters
* Tautulli viewing activity
* Read-only Radarr and Sonarr matching
* Review Queue and Leaving Soon tools
* Discord webhooks and optional `/search` bot integration
* Dark and light themes

## Screenshots

### Dashboard

See what's new, what's recently been watched, and what's happening across your Plex library.

![MyCouch Plex Dashboard](docs/screenshots/Dashboard.png)

### Smart Search

Describe what you feel like watching in natural language and let MyCouch search your Plex library for matching titles.

![MyCouch Plex Smart Search](docs/screenshots/SmartSearch.png)

### Server Stats

Explore Plex library size, storage usage, viewing activity and potential cleanup candidates.

![MyCouch Plex Server Stats](docs/screenshots/ServerStats.png)

### My History

Sign in with Plex to see your personal viewing history, watch time and most-played titles.

![MyCouch Plex Viewing History](docs/screenshots/MyHistory.png)

### Movies

Browse and analyse your movie library with viewing activity, file information and Radarr matching.

![MyCouch Plex Movie Library](docs/screenshots/Movies.png)

## Current release — v2.9.9

### What's new in v2.9.9

* Redesigned the Dashboard around real MyCouch, Plex and Tautulli data already held by the application.
* Added poster-based **Recently Added** and **Recently Watched** panels.
* Reorganised navigation so primary MyCouch features sit on the left and account, admin and display controls sit on the right.
* Moved **Welcome to MyCouch** to the top of the Dashboard.
* Moved Movies, TV Shows, Users and total Library Size summary cards to the top of **Server Stats**.
* Retained Smart Search, live **What's Playing on MyCouch?** and existing Tautulli activity.
* Improved the **What is MyCouch?** introduction and feature links.
* Improved Discord help and `/search` formatting.
* General layout and UI improvements.

### Other highlights

* Movies and TV tables with natural/numeric sortable columns.
* Played Count and popularity filters for 7/30/90 days, one year and all time.
* Plex browser/PIN sign-in for private **My History** viewing stats.
* Smart Search with Plex posters and **Open in Plex** links.
* Server Stats analysis, protected titles, Review Queue and Leaving Soon.
* Read-only Radarr/Sonarr matching.
* Tautulli-backed aggregate activity and personal history.
* Discord webhooks plus optional `/search` bot integration.
* Dark/light theme — light mode remains available by special request from Kyle, who apparently prefers staring into the sun.

### v2.9.6 fixes included

* **v2.9.6.1:** fixed the SQLite `NATURAL` collation syntax error.
* **v2.9.6.2:** fixed natural sorting for Unicode numeric characters such as superscript `²`.

## Fresh install on Windows

1. Install Python 3.
2. Extract MyCouch to a folder of your choice.
3. Run `start.ps1`.
4. Open `http://localhost:8090`.
5. Create the first admin account.
6. In **Settings**, select your Plex SQLite database and build the library cache.
7. Configure Tautulli, Radarr, Sonarr, Plex and Discord only if you want those integrations.

`start.ps1` creates a local `.venv` and installs the packages in `requirements.txt`.

You can optionally set `PLEX\_DB` before launch instead of selecting the database in Settings. See `.env.example` for an example; MyCouch does not automatically load `.env` files.

## Upgrade from LibraryLens

Stop LibraryLens first and make a backup of its folder.

Copy these existing runtime files into the new MyCouch folder:

* `auditor.db`
* `auditor-cache.db`
* `.pla-secret`

Keeping `.pla-secret` preserves existing remembered admin sessions. The legacy filenames are intentionally retained for compatibility.

Then run `start.ps1`. Your settings, protected titles, review queue, Tautulli cache, Arr matches, Discord settings and other local state remain in the existing databases.

## Security / privacy

Do **not** commit or publish your runtime databases or secret file. The supplied `.gitignore` excludes:

* `auditor.db` and SQLite sidecars
* `auditor-cache.db` and SQLite sidecars
* `.pla-secret`
* Plex snapshot files
* backups/logs
* `.env` files
* Python virtual environments and caches

API keys, Plex server tokens, Discord bot tokens/webhooks and private viewing identities are stored locally. Public pages expose aggregate activity rather than viewer identities.

Do not port-forward the Flask development server on port 8090 directly to the Internet. Use an HTTPS reverse proxy or secure tunnel if remote access is required.

## Plex sign-in

MyCouch uses Plex's browser/PIN authorization flow and never asks for a Plex password. The user sign-in token used to identify the account is not persisted as the user's login credential. Server-side Plex integration credentials configured by an administrator remain local.

## Discord

Outgoing webhooks can publish aggregate statistics, recommendations and Leaving Soon notices. The optional bot adds `/search`, returning MyCouch movie matches with posters and **Open in Plex** links. Bot tokens and webhook URLs must be entered locally and should never be committed to Git.

## GitHub

The project home is the **MyCouchApp** organisation and **MyCouch** repository.

Before any public push, verify the staged files with `git status` and confirm that no databases, tokens, webhooks, backups, logs or personal media paths are included.

