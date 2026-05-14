import ctypes
import os
import sys
from ctypes import wintypes

from PIL import Image, ImageGrab

from src.config import OCR_CAPTURE_SIZE
from src.logger import get_logger


logger = get_logger(__name__)

TARGET_EXE_NAMES = ("ShirenTheWanderer6.exe", "ShirenTheWanderer.exe")
TARGET_SIZE = OCR_CAPTURE_SIZE


class DirectCaptureError(RuntimeError):
    pass


if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def capture_shiren_window(target_size=TARGET_SIZE) -> Image.Image:
    """Steam版シレン6のウィンドウモードを直接キャプチャする。"""
    if sys.platform != "win32":
        raise DirectCaptureError("直接取得はWindows上でのみ利用できます")

    hwnd = _find_window_by_exe(TARGET_EXE_NAMES)
    if not hwnd:
        raise DirectCaptureError("Steam版シレン6の表示中ウィンドウが見つかりません")

    bbox = _client_bbox(hwnd)
    if not bbox:
        raise DirectCaptureError("ゲームウィンドウの取得範囲を特定できません")

    image = ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
    if image.size != target_size:
        image = image.resize(target_size, Image.Resampling.LANCZOS)
    return image


def _find_window_by_exe(exe_names):
    matches = []
    expected = {exe_name.lower() for exe_name in exe_names}

    @EnumWindowsProc
    def enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_path = _process_path(pid.value)
        if process_path and os.path.basename(process_path).lower() in expected:
            matches.append(hwnd)
            return False
        return True

    if not user32.EnumWindows(enum_proc, 0):
        error = ctypes.get_last_error()
        if error:
            logger.debug("EnumWindows error: %s", error)
    return matches[0] if matches else None


def _process_path(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def _client_bbox(hwnd):
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    top_left = wintypes.POINT(0, 0)
    bottom_right = wintypes.POINT(width, height)
    if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
        return None
    if not user32.ClientToScreen(hwnd, ctypes.byref(bottom_right)):
        return None

    return (top_left.x, top_left.y, bottom_right.x, bottom_right.y)
