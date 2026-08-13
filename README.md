# OD-rclone

OD-rclone is a cross-platform virtual-file bridge for public/open-directory search sources. It keeps stable virtual paths while remote origins can change, exposes the catalog over HTTP and read-only WebDAV, uses a sparse block cache for seekable media playback, and can hand completed downloads to Sonarr or Radarr.

> Use OD-rclone only with files you are authorized to access. An indexed or publicly reachable URL does not by itself grant permission to copy copyrighted material.

## Current status

The initial release implements the core architecture:

- ODCrawler structured search adapter
- EyeDex HTML search adapter
- MMNT best-effort/configurable adapter
- normalized search, regex filters, extension and size filters
- persistent SQLite virtual-file catalog
- multiple source URLs per virtual file
- HTTP `HEAD` and single-byte-range streaming
- sparse on-disk block cache with read-ahead
- read-only WebDAV (`PROPFIND`, `GET`, `HEAD`, `OPTIONS`)
- rclone-compatible WebDAV mount path
- native resumable HTTP downloader
- optional aria2 JSON-RPC downloader
- Sonarr/Radarr v3 status, missing-items and downloaded-scan bridge
- browser search/virtual-file/download UI
- Windows/Linux helper scripts
- Docker and Docker Compose
- Windows/Linux CI plus multi-architecture Docker build validation

Advanced source equivalence hashing, automatic Servarr wanted-item matching, full cache eviction policy enforcement, FTP random-access caching, native packaged executables and automatic container publishing are planned follow-ups.

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

The Web UI and API are exposed on port `8008`.

## Virtual files

Search results are not exposed directly as raw origin URLs. A result can be added to a stable virtual path such as:

```text
/TV/The Mentalist/Season 03/The Mentalist - S03E07.mkv
```

The catalog stores one or more source URLs behind that path. HTTP clients see the virtual file. OD-rclone can cache only the byte blocks a client actually reads.

## Plex / rclone

Create an rclone WebDAV remote:

```text
rclone config
  New remote: odrclone
  Storage: webdav
  URL: http://127.0.0.1:8008/webdav/
  Vendor: other
```

Linux example:

```bash
mkdir -p /mnt/odrclone
rclone mount odrclone: /mnt/odrclone --read-only --vfs-cache-mode off
```

Windows example:

```powershell
rclone mount odrclone: X: --read-only
```

Then point a Plex library at `/mnt/odrclone/TV`, `/mnt/odrclone/Movies`, or the equivalent Windows drive. OD-rclone itself provides the sparse media cache, so a second full rclone VFS cache is generally unnecessary for read-only playback.

### Plex-oriented behavior

A normal library probe does not automatically download the complete object. Reads are satisfied by byte range and stored as fixed-size cache blocks. A seek to the end of a large file therefore fetches the requested end blocks rather than the bytes before them, provided the origin honors HTTP ranges.

## API examples

Search:

```bash
curl -X POST http://localhost:8008/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"Example S01E01","extensions":["mkv","mp4"],"validate":false}'
```

Add a search result as a virtual file:

```text
POST /api/virtualize
```

List virtual files:

```text
GET /api/files
```

Stream a virtual path:

```text
GET /api/stream/Virtual/example.mkv
Range: bytes=0-1048575
```

## Sonarr / Radarr

Set each endpoint and API key in `config.yml`.

OD-rclone uses the v3 API and can call the supported downloaded-scan commands after a file has been completed into a directory visible to the corresponding Servarr instance.

```text
POST /api/servarr/sonarr/scan
POST /api/servarr/radarr/scan
```

Example body:

```json
{
  "path": "/downloads/od-rclone/job-123",
  "download_client_id": "od-rclone",
  "import_mode": "Move"
}
```

Sonarr command: `DownloadedEpisodesScan`  
Radarr command: `DownloadedMoviesScan`

## Provider notes

### ODCrawler

Uses the structured Elasticsearch-compatible endpoint captured from the public frontend. Extension filtering is done locally so OD-rclone does not depend on the frontend's generated `must_not` clauses.

### EyeDex

Uses `GET /search/?q=...&t=...` and parses direct external result links and available row metadata.

### MMNT

MMNT is primarily a browsable FTP index and its search form has changed over time. The adapter is intentionally isolated and `mmnt.search_url` is configurable. This prevents an MMNT frontend change from breaking the VFS or the other providers.

## Cache layout

Default block size: 8 MiB.

```text
data/cache/<virtual-file-id>/<block-index>.blk
```

The SQLite catalog records cached blocks and source metadata. Cache clearing is available through:

```text
DELETE /api/files/{id}/cache
```

## Security

The API can be protected with `auth.api_token`. Remote source URLs are currently visible to authenticated API callers and the local Web UI because they are useful for diagnostics; they are not exposed through WebDAV or normal virtual streaming URLs. Bind to localhost or a trusted LAN unless you configure a reverse proxy/authentication appropriate for your environment.

## Architecture

```text
EyeDex ─┐
ODCrawler ─┼─> Search coordinator -> virtual catalog -> sparse cache -> HTTP/WebDAV -> rclone/Plex
MMNT ───┘                              │
                                      ├-> native/aria2 downloads
                                      └-> Sonarr/Radarr downloaded scans
```
