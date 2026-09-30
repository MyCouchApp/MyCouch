# 🛋️ MyCouch

<img src="static/mycouch-github.png" alt="MyCouch couch mascot" width="180">

**Your media. Your history. What's next?**

MyCouch is a free, open-source, self-hosted companion for Plex Media Server. It brings library statistics, viewing activity, personal play history, Smart Search, media discovery and server information together in one simple dashboard.

MyCouch integrates with Plex, Tautulli, Radarr and Sonarr, with optional Discord integration for searching your Plex library using the `/search` command.

> MyCouch is an independent project and is not affiliated with Plex, Tautulli, Radarr, Sonarr, Discord, Emby or Jellyfin.

## Current release — v2.9.11

### MyCouch is now installable as an app

v2.9.11 introduces Progressive Web App (PWA) support alongside a major Dashboard and navigation redesign.

When MyCouch is accessed over HTTPS or localhost in a supported browser, it can now be installed and launched in its own standalone app window.

### What's new in v2.9.11

- Added Progressive Web App (PWA) support.
- Added **Install MyCouch** when installation is available.
- MyCouch can now launch in its own standalone app window.
- Added MyCouch application icons, web app manifest and lightweight service worker.
- Redesigned navigation around a responsive left-hand sidebar.
- Moved Plex, Changelog, Admin and theme controls into the sidebar.
- Added a new **Welcome to MyCouch** Dashboard.
- Added visual shortcuts for Smart Search, Movies, TV Shows, My History and Server Stats.
- Added MyCouch couch artwork throughout the new interface.
- Retained Recently Added and Recently Watched poster panels.
- Retained Smart Search and live **What's Playing on MyCouch?** activity.
- Added responsive navigation for smaller screens.
- General layout, spacing and UI improvements.

### Progressive Web App

MyCouch's service worker only caches static application assets such as stylesheets, icons and artwork.

Plex history, Tautulli activity, authentication, library information and other dynamic data continue to come directly from your live MyCouch server.

For installation from another device, MyCouch should be served over HTTPS. Localhost can also be used for local installation.

### What's new in v2.9.10

- Added the approved MyCouch couch artwork to the dashboard and section headings, with a light-theme logo and a compact GitHub avatar.
- Preserved the v2.9.9 dashboard redesign, poster panels and split navigation.

### What's new in v2.9.9

- Redesigned the Dashboard around real MyCouch/Plex/Tautulli data already held by the application.
- Added Movies, TV Shows, Users and total Library Size summary cards.
- Added poster-based Recently Added and Recently Watched panels.
- Split navigation into primary features on the left and secondary/account controls on the right.
- Retained Smart Search, live What's Playing on MyCouch? and Tautulli activity on the Dashboard.

MyCouch was originally known as **LibraryLens**. Existing LibraryLens databases remain compatible with MyCouch.

## Features

- **What's Playing on MyCouch?** live activity on the Dashboard.
- Recently Added and Recently Watched poster panels.
- Movies and TV tables with natural/numeric sortable columns.
- Played Count and popularity filters for 7/30/90 days, one year and all time.
- Plex browser/PIN sign-in for private **My History** viewing stats.
- Smart Search with Plex posters and Open in Plex links.
- Server Stats for understanding your Plex library.
- Cleanup analysis, protected titles, Review Queue and Leaving Soon.
- Read-only Radarr/Sonarr matching.
- Tautulli-backed aggregate activity and personal history.
- Discord webhooks plus optional `/search` bot integration.
- Installable Progressive Web App.
- Responsive desktop/mobile interface.
- Dark and light themes — light mode remains available by special request from Kyle, who apparently prefers staring into the sun.

### v2.9.6 fixes included

- **v2.9.6.1:** fixed the SQLite `NATURAL` collation syntax error.
- **v2.9.6.2:** fixed natural sorting for Unicode numeric characters such as superscript `²`.

## Screenshots

The screenshots below show MyCouch's Plex library, viewing history and server tools. The Plex account panel in My History has been obscured for privacy.

### Dashboard

![Dashboard with Recently Added and Recently Watched posters](docs/screenshots/dashboard.png)

### My History

![Personal viewing history](docs/screenshots/my-history.png)

### Server Stats

![Server statistics](docs/screenshots/server-stats.png)

### Movies

![Movies library](docs/screenshots/movies.png)

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

## Install MyCouch as an app

Once MyCouch is running, supported browsers can install it as a Progressive Web App.

If **Install MyCouch** appears in the sidebar:

1. Select **Install MyCouch**.
2. Confirm the browser's installation prompt.
3. MyCouch will be installed on your computer or device and can launch in its own window.

For installation from another device, MyCouch should be served over HTTPS.

Installing the app does not create an offline copy of your Plex data. MyCouch continues to use your live server for library, history and activity information.

## Upgrade an existing installation

Stop MyCouch or LibraryLens first and make a backup of the existing folder.

Preserve these runtime files when moving to a new MyCouch installation:

- `auditor.db`
- `auditor-cache.db`
- `.pla-secret`

Keeping `.pla-secret` preserves existing remembered admin sessions. The legacy filenames are intentionally retained for compatibility.

Then run `start.ps1`.

Your settings, protected titles, review queue, Tautulli cache, Arr matches, Discord settings and other local state remain in the existing databases.

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

MyCouch uses Plex's browser/PIN authorization flow and never asks for a Plex password.

The user sign-in token used to identify the account is not persisted as the user's login credential. Server-side Plex integration credentials configured by an administrator remain local.

## Discord

Outgoing webhooks can publish aggregate statistics, recommendations and Leaving Soon notices.

The optional bot adds `/search`, returning MyCouch movie matches with posters and Open in Plex links.

Bot tokens and webhook URLs must be entered locally and should never be committed to Git.

## GitHub

The project is maintained under the **MyCouchApp** organisation in the **MyCouch** repository.

Before any public push, verify the staged files with `git status` and confirm that no databases, tokens, webhooks, backups, logs or personal media paths are included.

The artwork sheet is `static/mycouch-artwork.jpg`; the square GitHub avatar is `static/mycouch-github.png`.

## License

MyCouch is released under the MIT License.