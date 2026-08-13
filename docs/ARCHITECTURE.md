# Architecture

OD-rclone treats a virtual path as the stable identity and source URLs as replaceable backing objects.

## Invariants

1. A virtual file can have multiple candidate sources.
2. Clients never need to know which source currently backs the path.
3. A known file size is required before random-access streaming.
4. The cache is sparse and block-addressed, not a single partial sequential file.
5. Source failure cannot delete the virtual catalog entry.
6. Provider failures are isolated from each other.

## Read path

`GET/Range -> catalog lookup -> block calculation -> cache lookup -> source selection -> ranged origin request -> cache block -> client`

## Download path

`virtual file -> best source -> native/aria2 -> completed path -> optional Servarr Downloaded*Scan command`

## Source failover

The initial release retries another source when fetching a cache block if the selected source fails. It does not yet prove byte identity between differently sized or differently encoded copies. A future equivalence layer will use exact size, container metadata and sampled block hashes before allowing seamless cross-source block mixing.
