# OD-rclone

OD-rclone is a cross-platform virtual-file bridge for public/open-directory search sources. It keeps stable virtual paths while remote origins can change, exposes the catalog over HTTP and read-only WebDAV, uses a sparse block cache for seekable media playback, and can hand completed downloads to Sonarr or Radarr.

> Use OD-rclone only with files you are authorized to access. An indexed or publicly reachable URL does not by itself grant permission to copy copyrighted material.

## Current status

The initial release implements a working core architecture:

- ODCrawler structured search adapter
- EyeDex HTML search adapter
- MMNT best-effort/configurable adapter
- normalized search, regex filters, extension and size filters
- persistent SQLite virtual-file catalog
- multiple source URLs per virtual file
- HTTP `HEAD` and single-byte-range streaming
- HTTP/HTTPS and FTP/FTPS source validation
- sparse on-disk block cache with read-ahead and size limits
- `REMOTE_ONLY`, `TEMP`, `FULL_ON_PLAY`, and `PIN` cache behavior
- read-only WebDAV (`PROPFIND`, `GET`, `HEAD`, `OPTIONS`)
- rclone-compatible WebDAV mount path
- native resumable HTTP/FTP downloader
- optional aria2 JSON-RPC downloader
- Sonarr/Radarr v3 status, missing-items, autofill matching, and downloaded-scan bridge
- browser search/virtual-file/download UI
- Windows/Linux helper scripts
- Docker and Docker Compose
- Windows/Linux CI plus multi-architecture Docker build validation
- tag-triggered Windows/Linux executable builds and GHCR multi-architecture image publishing

Strong cross-source equivalence hashing, richer host-speed scoring, multi-range HTTP responses, and seamless verified byte-level mirror switching remain follow-up work.

## Quick start: Linux

```bash
git clone https://github.com/uhuhuhuhuhuhuhuh/OD-rclone.git
cd OD-rclone
cp config.example.yml config.yml
./scripts/run-linux.sh
```

Open `http://localhost:8008`.

## Quick start: Windows

Install Python 3.11+ and run PowerShell:

```powershell
git clone https://github.com/uhuhuhuhuhuhuhuh/OD-rclone.git
cd OD-rclone
Copy-Item config.example.yml config.yml
.\scripts\run-windows.ps1
```

For an rclone filesystem mount on Windows, install WinFsp first.

## Docker

```bash
cp config.example.yml config.yml
docker compose up -d --build
```

The Web UI and API are exposed on port `8008`. Tagged releases also publish `ghcr.io/uhuhuhuhuhuhuhuh/od-rclone` for `linux/amd64` and `linux/arm64`.

## Virtual files

Search results can be assigned stable paths such as:

```text
/TV/The Mentalist/Season 03/The Mentalist - S03E07.mkv
```

The catalog stores one or more source URLs behind that path. WebDAV, rclone and Plex see the virtual path instead of needing to know which origin currently backs it.

## Plex / rclone

Create an rclone WebDAV remote:

```text
rclone config
  New remote: odrclone
  Storage: webdav
  URL: http://127.0.0.1:8008/webdav/
  Vendor: other
```

Linux:

```bash
mkdir -p /mnt/odrclone
rclone mount odrclone: /mnt/odrclone --read-only --vfs-cache-mode off
```

Windows:

```powershell
rclone mount odrclone: X: --read-only
```

Point Plex at `/mnt/odrclone/TV`, `/mnt/odrclone/Movies`, or the equivalent Windows drive. A normal probe does not intentionally download the entire object. OD-rclone fetches fixed-size blocks corresponding to requested byte ranges and can read ahead without allocating the full virtual file.

## API

Search:

```bash
curl -X POST http://localhost:8008/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"Example S01E01","extensions":["mkv","mp4"],"validate":true}'
```

Important routes:

```text
POST   /api/search
POST   /api/virtualize
GET    /api/files
GET    /api/files/{id}
DELETE /api/files/{id}/cache
POST   /api/downloads
GET    /api/downloads
GET    /api/stream/{virtual-path}
GET    /api/servarr/{sonarr|radarr}/missing
POST   /api/servarr/{sonarr|radarr}/autofill
POST   /api/servarr/{sonarr|radarr}/scan
```

## Sonarr / Radarr

Set each URL and API key in `config.yml`. OD-rclone can query missing items, derive title/season/episode or movie/year searches, virtualize the best candidate, download it, and issue the corresponding downloaded-scan command after completion.

Sonarr command: `DownloadedEpisodesScan`  
Radarr command: `DownloadedMoviesScan`

This is a companion bridge rather than a patched Sonarr/Radarr build, so it does not appear as a new native download-client type inside their built-in provider menus.

## Providers

### ODCrawler

Uses the structured search endpoint captured from the public frontend. Extension filtering is intentionally done locally rather than reproducing the frontend's generated `must_not` clauses. The optional public link-alive endpoint is used as a first-pass health signal.

### EyeDex

Uses `GET /search/?q=...&t=...` and parses external result links plus row metadata such as displayed size when available.

### MMNT

MMNT is primarily a browsable FTP index and its search form has changed over time. The adapter is isolated and `mmnt.search_url` is configurable. FTP/FTPS targets themselves support validation, resumed downloading, and ranged cache reads when the server supports `REST`.

## Cache

Default block size is 8 MiB:

```text
data/cache/<virtual-file-id>/<block-index>.blk
```

The cache supports read-ahead, maximum-size/minimum-free-space enforcement, manual clearing, pinning, full-on-play prefetch and remote-only reads.

## Security

The REST API can be protected with `auth.api_token` and WebDAV can use Basic credentials. Source URLs are not exposed through normal WebDAV paths or virtual stream URLs. Bind to localhost or a trusted LAN unless you configure appropriate authentication/reverse-proxy controls.

## Architecture

```text
EyeDex ─┐
ODCrawler ─┼─> Search coordinator -> virtual catalog -> sparse cache -> HTTP/WebDAV -> rclone/Plex
MMNT ───┘                              │
                                      ├-> native/aria2 downloads
                                      └-> Sonarr/Radarr missing/import bridge
```
