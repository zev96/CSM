"""反馈持久层测试装置：每测一个 tmp monitor.db（含 v9 四表），重置模块单例。

共享盘红线 + tmp DB 铁律：绝不碰真实 monitor.db。
"""
import threading
from pathlib import Path

import pytest

from csm_core.monitor import storage as monitor_storage


@pytest.fixture
def fresh_db(tmp_path: Path):
    monitor_storage._db_path = None
    monitor_storage._initialized = False
    monitor_storage._local = threading.local()
    monitor_storage.init_db(tmp_path / "monitor.db")
    yield tmp_path / "monitor.db"
    conn = getattr(monitor_storage._local, "conn", None)
    if conn is not None:
        conn.close()
    monitor_storage._db_path = None
    monitor_storage._initialized = False
    monitor_storage._local = threading.local()
