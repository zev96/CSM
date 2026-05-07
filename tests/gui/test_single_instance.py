"""SingleInstance: only the first process binds the local server."""
from __future__ import annotations
from csm_gui.tray.single_instance import SingleInstance


def test_first_instance_acquires():
    inst = SingleInstance(server_name="csm-test-singleton-1")
    assert inst.try_acquire() is True
    inst.release()


def test_second_instance_detects_running():
    a = SingleInstance(server_name="csm-test-singleton-2")
    b = SingleInstance(server_name="csm-test-singleton-2")
    assert a.try_acquire() is True
    assert b.try_acquire() is False  # 第二个失败
    a.release()


def test_show_signal_emitted_on_second_launch(qtbot):
    """第二个实例发 'show' 命令后第一个的 show_requested signal 应触发。"""
    a = SingleInstance(server_name="csm-test-singleton-3")
    b = SingleInstance(server_name="csm-test-singleton-3")
    assert a.try_acquire() is True
    assert b.try_acquire() is False

    with qtbot.waitSignal(a.show_requested, timeout=2000):
        b.send_show()

    a.release()


def test_stale_socket_cleaned_up():
    """如果有陈旧 socket 残留，第二次启动应能清理后正常 acquire。"""
    a = SingleInstance(server_name="csm-test-singleton-4")
    assert a.try_acquire() is True
    # 不调 release，模拟崩溃
    del a

    # 第二次启动应能清理并成功
    b = SingleInstance(server_name="csm-test-singleton-4")
    assert b.try_acquire() is True
    b.release()
