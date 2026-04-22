from csm_core.framework.trace import FrameworkTrace


def test_empty_trace_has_no_entries():
    t = FrameworkTrace()
    assert t.entries == []
    assert t.to_dict() == {"entries": []}


def test_skipped_empty_slot_records_entry():
    t = FrameworkTrace()
    t.skipped_empty_slot("slot_5", block_index=4)
    assert t.entries == [
        {"event": "skipped_empty_slot", "slot_id": "slot_5", "block_index": 4}
    ]


def test_missing_meta_records_entry_with_copied_keys():
    t = FrameworkTrace()
    keys = ["品牌", "关键词"]
    t.missing_meta(block_index=7, pick_index=1, missing_keys=keys)
    # Mutating the original list must NOT affect the recorded entry.
    keys.append("mutated")
    assert t.entries == [{
        "event": "missing_meta",
        "block_index": 7,
        "pick_index": 1,
        "missing_keys": ["品牌", "关键词"],
    }]
