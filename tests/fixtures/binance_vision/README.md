# Binance Vision test fixtures

These are real, unmodified monthly kline zips downloaded from
`https://data.binance.vision/data/spot/monthly/klines/`. They are committed
into the repo so the test suite has deterministic, offline-capable inputs for
the Phase 2 loader.

| File | Source URL | Approx size | SHA256 |
|---|---|---|---|
| `BTCUSDT-1m-2024-01.zip` | https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2024-01.zip | ~2.1 MB | `40b78258091a468f8756843f207f5913eafc1d6e756c40a78711320d93fa5e75` |

## Refreshing

Binance Vision files are immutable historical snapshots; refresh is normally
unnecessary. To re-pull (e.g. after a corrupted clone), drop into a Python
shell at the repo root:

```python
import urllib.request
url = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2024-01.zip"
urllib.request.urlretrieve(url, "tests/fixtures/binance_vision/BTCUSDT-1m-2024-01.zip")
urllib.request.urlretrieve(url + ".CHECKSUM",
    "tests/fixtures/binance_vision/BTCUSDT-1m-2024-01.zip.CHECKSUM")
```

Then verify against the table above (or recompute):

```python
import hashlib, pathlib
print(hashlib.sha256(pathlib.Path(
    "tests/fixtures/binance_vision/BTCUSDT-1m-2024-01.zip"
).read_bytes()).hexdigest())
```
