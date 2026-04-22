"""One-shot migration: fold framework.json into template.blocks.

Usage::

    python scripts/migrate_framework_to_blocks.py \
        --templates-dir templates \
        --frameworks-dir frameworks \
        [--apply]  # default dry-run prints summary only

Rules:
  1. For each template *.json in old schema (has top-level ``slots`` key):
     - Look up its framework by ``default_framework`` id, or a sibling
       framework whose basename matches the template basename.
     - If no framework found: skip with warning.
     - If framework has a ``brand_reason_list`` block: skip with warning
       (requires manual conversion to hero_brand + competitor_pool).
     - Otherwise: build new ``blocks`` list by walking framework.blocks,
       replacing ``paragraph`` / ``numbered_list`` with the full slot
       object (source / pick_notes / children) from the template.
  2. Back up original template to ``templates/_migrated_backup/`` before
     overwriting.
  3. Idempotent: skip any template already in new schema (has ``blocks``).
"""
from __future__ import annotations
import argparse
import json
import shutil
from pathlib import Path


def _is_new_schema(data: dict) -> bool:
    return "blocks" in data and "slots" not in data


def _find_framework(fw_dir: Path, tpl_path: Path, default_id: str | None) -> Path | None:
    if default_id:
        for p in fw_dir.glob("*.json"):
            if p.stem == default_id:
                return p
    candidate = fw_dir / f"{tpl_path.stem}.json"
    if candidate.exists():
        return candidate
    return None


def _slots_by_id(slots: list[dict]) -> dict[str, dict]:
    return {s["id"]: s for s in slots}


def _slot_to_paragraph_block(slot: dict) -> dict:
    return {
        "kind": "paragraph",
        "id": slot["id"],
        "label": slot.get("label", ""),
        "source": slot["source"],
        "pick_notes": slot.get("pick_notes", 1),
        "pick_variants_per_note": slot.get("pick_variants_per_note", 1),
        "constraints": slot.get("constraints", []),
        "depends_on": slot.get("depends_on", []),
        "children": [_slot_to_paragraph_block(c) for c in slot.get("children", [])],
    }


def _slot_to_numbered_list_block(slot: dict) -> dict:
    pn = slot.get("pick_notes", 3)
    return {
        "kind": "numbered_list",
        "id": slot["id"],
        "label": slot.get("label", ""),
        "source": slot["source"],
        "pick_notes": pn if isinstance(pn, (int, dict)) else 3,
        "number_style": "1.",
        "item_separator": "\n\n",
    }


def _heading_block(fb: dict) -> dict:
    return {
        "kind": "heading",
        "id": f"h_{fb.get('index') or 'x'}",
        "level": fb.get("level", 2),
        "index": fb.get("index", ""),
        "text": fb["text"],
    }


def _literal_block(fb: dict) -> dict:
    return {"kind": "literal", "id": "lit", "text": fb["text"]}


def _convert_blocks(
    fw_blocks: list[dict], slots: list[dict],
) -> tuple[list[dict] | None, str | None]:
    sb = _slots_by_id(slots)
    out: list[dict] = []
    used_heading_ids: set[str] = set()
    for fb in fw_blocks:
        kind = fb["kind"]
        if kind == "brand_reason_list":
            return None, "framework uses brand_reason_list — manual rewrite required"
        if kind == "paragraph":
            slot = sb.get(fb["slot"])
            if slot is None:
                return None, f"framework references unknown slot '{fb['slot']}'"
            out.append(_slot_to_paragraph_block(slot))
        elif kind == "numbered_list":
            slot = sb.get(fb["slot"])
            if slot is None:
                return None, f"framework references unknown slot '{fb['slot']}'"
            out.append(_slot_to_numbered_list_block(slot))
        elif kind == "heading":
            blk = _heading_block(fb)
            base = blk["id"]
            i = 1
            while blk["id"] in used_heading_ids:
                i += 1
                blk["id"] = f"{base}_{i}"
            used_heading_ids.add(blk["id"])
            out.append(blk)
        elif kind == "literal":
            blk = _literal_block(fb)
            idx = sum(1 for b in out if b.get("id", "").startswith("lit"))
            blk["id"] = f"lit_{idx + 1}"
            out.append(blk)
        else:
            return None, f"unknown framework block kind '{kind}'"
    return out, None


def migrate(templates_dir: Path, frameworks_dir: Path, *, apply: bool = True) -> dict:
    tpl_dir = Path(templates_dir)
    fw_dir = Path(frameworks_dir)
    backup_dir = tpl_dir / "_migrated_backup"

    report: dict[str, list[str]] = {
        "migrated": [], "skipped": [], "skipped_already_new": [],
    }

    for tpl_path in sorted(tpl_dir.glob("*.json")):
        data = json.loads(tpl_path.read_text(encoding="utf-8"))
        if _is_new_schema(data):
            report["skipped_already_new"].append(tpl_path.name)
            continue
        fw_path = _find_framework(
            fw_dir, tpl_path, data.get("default_framework"),
        )
        if fw_path is None:
            report["skipped"].append(tpl_path.name)
            print(f"SKIP {tpl_path.name}: no framework found")
            continue
        fw_data = json.loads(fw_path.read_text(encoding="utf-8"))
        new_blocks, err = _convert_blocks(fw_data["blocks"], data.get("slots", []))
        if err:
            report["skipped"].append(tpl_path.name)
            print(f"SKIP {tpl_path.name}: {err}")
            continue
        new_data = {
            "id": data["id"], "name": data["name"],
            "product": data["product"], "version": data.get("version", 1),
            "system_prompt_default": data.get("system_prompt_default", ""),
            "seo_defaults": data.get("seo_defaults", {}),
            "blocks": new_blocks,
        }
        if apply:
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tpl_path, backup_dir / tpl_path.name)
            tpl_path.write_text(
                json.dumps(new_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        report["migrated"].append(tpl_path.name)
        print(f"OK {tpl_path.name}")

    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--templates-dir", default="templates")
    ap.add_argument("--frameworks-dir", default="frameworks")
    ap.add_argument("--apply", action="store_true", help="write changes (default dry-run)")
    args = ap.parse_args()
    report = migrate(Path(args.templates_dir), Path(args.frameworks_dir), apply=args.apply)
    print("\n== summary ==")
    for k, v in report.items():
        print(f"{k}: {len(v)} — {v}")
    print(f"(apply={args.apply})")


if __name__ == "__main__":
    main()
