# Vendored code from MediaCrawler

This directory contains code adapted from
[NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler).

## License

MediaCrawler is licensed under **NON-COMMERCIAL LEARNING LICENSE 1.1**.

The vendored files in this directory are used under the same license. **CSM
is a personal / team-internal learning tool**, not a commercial product, so
vendoring here is within the original license's "non-commercial learning
purposes" grant. If CSM is ever forked or redistributed under different
terms, these vendored files must be removed or replaced first.

Per the upstream license, this software must not be used for:
- any commercial purpose without written consent of the copyright owner
- large-scale crawling or activities that disrupt platform operations
- any unlawful or improper use

See `reference/MediaCrawler/LICENSE` for the full license text after
running:

```sh
git clone --depth=1 https://github.com/NanmiCoder/MediaCrawler.git reference/MediaCrawler
```

The license file is reproduced in English and Chinese in the upstream repo.

## Source

- **Upstream repo**: https://github.com/NanmiCoder/MediaCrawler
- **Commit at vendor time**: `f328ee35b55e25e8aaeb9c847fe8b622e3f3447f`
- **Date vendored**: 2026-05-18

## Files

| Local file | Upstream source | Purpose |
|---|---|---|
| `mc_bilibili_sign.py` | `media_platform/bilibili/help.py` (BilibiliSign class only) | WBI w_rid/wts signing for Bilibili web API |
| `mc_kuaishou_search.graphql` | `media_platform/kuaishou/graphql/search_query.graphql` | `visionSearchPhoto` GraphQL operation template |

## Local modifications

`mc_bilibili_sign.py`:
- Removed unused imports (`model.m_bilibili`, `tools.utils`)
- Inlined `utils.get_unix_timestamp()` as `int(time.time())`
- Dropped `parse_video_info_from_url` / `parse_creator_info_from_url`
  (CSM keeps URL parsing in `csm_core/mining/platforms/bilibili_search.py`)
- Promoted `map_table` from instance attribute to a class-level constant
  `MAP_TABLE` (tuple — immutable, no per-instance allocation)
- Reformatted to match the rest of `csm_core/`

`mc_kuaishou_search.graphql`: **bit-identical** to upstream — no comments
or whitespace changes. Kuaishou's GraphQL server has been observed to
validate against a strict query hash in some configurations, so we keep
the operation body byte-for-byte. Attribution lives in this README only.

## Update protocol

If WBI signing or the GraphQL schema breaks (typically once every 6–12 mo
on upstream changes), re-sync:

1. `cd reference/MediaCrawler && git pull && git rev-parse HEAD`
2. Diff against the vendored copy:
   ```sh
   diff reference/MediaCrawler/media_platform/bilibili/help.py \
        csm_core/mining/platforms/_vendor/mc_bilibili_sign.py
   ```
3. Re-apply the local modifications above
4. Bump `commit at vendor time` in this README
