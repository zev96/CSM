"""Framework e2e test — will be deleted in Task 10.

This test relied on frameworks_dir kwarg in GenerateRequest which was
removed in Task 7. Skipped until framework layer cleanup in Task 10.
"""
import pytest

pytest.skip("framework layer removed from pipeline (Task 7); cleanup in Task 10", allow_module_level=True)
