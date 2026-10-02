# 🛋️ MyCouch

<img src="static/mycouch-github.png" alt="MyCouch couch mascot" width="180">

**Your media. Your history. What's next?**

MyCouch is a self-hosted companion for exploring and understanding a Plex media library. It combines library analysis, viewing activity, discovery/search, personal play history, cleanup review, Radarr/Sonarr matching, Tautulli activity and optional Discord integration.

> MyCouch is an independent project and is not affiliated with Plex, Tautulli, Radarr, Sonarr, Discord, Emby or Jellyfin.

## Current release — v2.9.13

### Server Stats Gets a Makeover

v2.9.13 gives Server Stats and the Movie/TV detail pages a more visual, useful interface while improving how MyCouch handles long-term Tautulli history.

- Redesigned **Popular Movies** and **Popular TV** as compact Top 10 poster grids.
- Added ranking badges and hover details for viewers, plays, and viewing hours.
- Redesigned Movie detail pages with artwork, metadata, activity, storage, video information, Plex links, and Radarr status.
- Redesigned TV detail pages with artwork, season/episode information, activity, storage, quality information, Plex links, and Sonarr status.
- Popular titles link directly to their detail pages.
- Historical title and year information from Tautulli is now retained locally during sync.
- If Plex recreates an item with a new rating key, MyCouch can match the historical title/year to the current library item.
- Relinked titles use the current Plex poster and working detail page while retaining their historical viewing statistics.
- Items genuinely no longer in Plex remain represented in historical statistics instead of exposing obsolete Plex IDs.
- Dashboard rendering remains local-only; historical recovery no longer requires a live Tautulli request during page load.

### v2.9.12 — Smarter Smart Search

v2.9.12 focuses on making Smart Search behave like a natural-language search of your Plex library rather than a loose keyword search.

- Added strict year and decade constraints, including searches such as `from 1994`, `from the 90s`, and `from the 1980s`.
- Added genre-aware search intent for common genres and phrases such as `funny`, `sci-fi`, `horror`, and `romantic`.
- Added watched and unwatched constraints tied to Plex viewing data.
- Added runtime parsing for searches such as `under 90 minutes`, `less than 2 hours`, `over 2 hours`, and `around 90 minutes`.
- Added **Smart Search understood** so you can see how MyCouch interpreted a natural-language query.
- Search results now enforce requested constraints instead of filling the page with increasingly weak matches.
- Improved result ranking so equally relevant titles are no longer automatically ordered newest-first.
- Improved match labels so **Strong match**, **Good match**, and **Possible match** reflect the actual query.
- Added an explicit **Show closest matches** fallback when no exact result exists.
- Closest matches relax constraints in a predictable order: runtime first, then watched status, then year. Core genre intent remains strict.
- Recent searches are now stored per signed-in Plex user; signed-out visitors use the shared search history.
- Added a **Clear history** control for the current user's search history.
- Updated the sidebar version display to use the application version instead of a hard-coded release number.

### v2.9.11 — Installable MyCouch app and interface redesign

- Added Progressive Web App (PWA) support.
- MyCouch can be installed from supported desktop and mobile browsers and launched in its own standalone app window.
- Added application icons, web app manifest, and a lightweight service worker for static assets.
- Added an **Install MyCouch** option when installation is available.
- Redesigned navigation around a responsive left-hand sidebar.
- Moved Plex, Changelog, Admin, and display controls into the sidebar.
- Redesigned the Dashboard with a new **Welcome to MyCouch** hero and visual shortcuts.
- Added Recently Added and Recently Watched panels while retaining live What's Playing and activity information.
- Added MyCouch couch artwork throughout the interface.
- The PWA does not cache Plex history, Tautulli activity, authenticated pages, or other dynamic/private data.


## Screenshots

These prepared screenshots show the v2.9.9 layout before the couch artwork was added in v2.9.10. The Plex account panel in My History is obscured.

### Dashboard

![Dashboard with Recently Added and Recently Watched posters](docs/screenshots/Dashboard.png)

### My History

![Personal viewing history](docs/screenshots/my-history.png)

### Server Stats

![Server statistics](docs/screenshots/server-stats.png)

### Movies

![Movies library](docs/screenshots/Movies.png)

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

The artwork sheet is `static/mycouch-artwork.jpg`; the square GitHub avatar is `static/mycouch-github.png`.
