"""Masked local credential input. Never logs, saves, or sends keys to the browser."""
from getpass import getpass
import os

WINDOWS = os.name == 'nt'


def credential_error(value):
    if not value:
        return '尚未输入密钥'
    if len(value) < 8:
        return '密钥输入不完整，请重新粘贴完整API密钥'
    if not value.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in value):
        return '密钥含空白、控制字符或非英文字符，请重新粘贴完整密钥'
    if value.lower().startswith('bearer') or value[0] in ('"', "'") or value[-1] in ('"', "'"):
        return '只需粘贴密钥本身，不要包含Bearer前缀或引号'
    return None


def _windows_secret(prompt):
    import tkinter as tk
    from tkinter import simpledialog
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        value = simpledialog.askstring('衡研 · 模型API密钥', prompt + '\n请在此输入框按 Ctrl+V 粘贴完整密钥。\n输入会遮蔽，不写入文件。', show='*', parent=root)
    finally:
        root.destroy()
    if value is None:
        raise ValueError('已取消密钥输入，未启动模型调用')
    return value


def read_api_key(prompt, optional=False):
    use_dialog = WINDOWS
    while True:
        if use_dialog:
            try:
                raw = _windows_secret(prompt)
            except ImportError:
                use_dialog = False
                print('图形输入不可用：请在控制台右键粘贴密钥，不要按Ctrl+V。')
                continue
            except Exception as exc:
                if type(exc).__name__ != 'TclError':
                    raise
                use_dialog = False
                print('图形输入不可用：请在控制台右键粘贴密钥，不要按Ctrl+V。')
                continue
        else:
            raw = getpass(prompt)
        value = raw.strip()
        if optional and not value:
            return ''
        message = credential_error(value)
        if not message:
            return value
        print(message + '；当前不会调用模型。')
