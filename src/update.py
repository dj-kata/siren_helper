#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import re
import json
import requests
import shutil
import shlex
import subprocess
import threading
import time
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from packaging import version

import traceback
from bs4 import BeautifulSoup
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from src.logger import get_logger
logger = get_logger(__name__)


GITHUB_REPOSITORY = "dj-kata/siren_helper"
RELEASE_TAG_PREFIX = "siren6"
RELEASE_ASSET_NAME = "siren6_helper.zip"
APP_FOLDER_NAME = "siren6_helper"
EXE_NAME = "siren6_helper.exe" if sys.platform == "win32" else "siren6_helper"


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    current_version: str
    asset_url: str
    release_url: str


class AutoUpdater(QObject):
    update_found = Signal(object)
    check_failed = Signal(str)
    install_failed = Signal(str)
    install_ready = Signal(str)

    def __init__(self, parent: QWidget, current_version: str) -> None:
        super().__init__(parent)
        self._parent = parent
        self._current_version = current_version

    def start(self) -> None:
        thread = threading.Thread(target=self._check_worker, daemon=True)
        thread.start()

    def install(self, info: UpdateInfo) -> None:
        thread = threading.Thread(target=self._install_worker, args=(info,), daemon=True)
        thread.start()

    def _check_worker(self) -> None:
        try:
            info = check_for_qt_updates(self._current_version)
        except Exception as exc:
            logger.error(traceback.format_exc())
            self.check_failed.emit(str(exc))
            return

        if info is not None:
            self.update_found.emit(info)

    def _install_worker(self, info: UpdateInfo) -> None:
        try:
            script_path = prepare_qt_update(info)
        except Exception as exc:
            logger.error(traceback.format_exc())
            self.install_failed.emit(str(exc))
            return

        self.install_ready.emit(str(script_path))


def start_auto_update_check(parent: QWidget, current_version: str) -> None:
    if not getattr(sys, "frozen", False):
        return

    updater = AutoUpdater(parent, current_version)
    parent._auto_updater = updater  # type: ignore[attr-defined]
    updater.update_found.connect(lambda info: _prompt_qt_update(parent, updater, info))
    updater.install_ready.connect(_run_qt_update_script)
    updater.install_failed.connect(lambda message: _show_qt_install_error(parent, message))
    updater.start()


def app_root() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()


def check_for_qt_updates(current_version: str) -> UpdateInfo | None:
    release = _fetch_latest_siren6_release()
    if release is None:
        return None

    latest_version = str(release.get("tag_name") or release.get("name") or "").strip()
    latest_for_compare = _extract_prefixed_version(latest_version)
    current_for_compare = _extract_optional_prefixed_version(current_version)
    if latest_for_compare is None or current_for_compare is None:
        logger.info(f"version parse failed: latest={latest_version}, current={current_version}")
        return None
    if latest_for_compare <= current_for_compare:
        return None

    asset_url = _asset_download_url(release)
    if not asset_url:
        logger.info(f"release asset not found: {RELEASE_ASSET_NAME}")
        return None

    return UpdateInfo(
        version=latest_version,
        current_version=current_version or "0.0.0",
        asset_url=asset_url,
        release_url=str(release.get("html_url") or ""),
    )


def prepare_qt_update(info: UpdateInfo) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="siren6_helper_update_"))
    archive_path = temp_dir / RELEASE_ASSET_NAME
    extract_dir = temp_dir / "extract"
    _download_file(info.asset_url, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(extract_dir)

    source_dir = _find_extracted_app_dir(extract_dir)
    if source_dir is None:
        raise RuntimeError("更新ファイル内にアプリ本体が見つかりませんでした。")

    return _write_qt_update_script(source_dir, app_root(), Path(sys.executable).resolve())


def _prompt_qt_update(parent: QWidget, updater: AutoUpdater, info: UpdateInfo) -> None:
    result = QMessageBox.question(
        parent,
        "アップデート確認",
        (
            "新しいバージョンが利用可能です。\n\n"
            f"現在: {info.current_version}\n"
            f"最新: {info.version}\n\n"
            "ダウンロードして更新しますか？"
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if result == QMessageBox.StandardButton.Yes:
        updater.install(info)


def _show_qt_install_error(parent: QWidget, message: str) -> None:
    QMessageBox.warning(
        parent,
        "アップデート失敗",
        f"アップデートを準備できませんでした。\n\n{message}",
    )


def _run_qt_update_script(script_path_text: str) -> None:
    script_path = Path(script_path_text)
    if sys.platform.startswith("win"):
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
            ],
            close_fds=True,
        )
    else:
        subprocess.Popen([str(script_path)], close_fds=True)

    app = QApplication.instance()
    if app is not None:
        app.quit()


def _fetch_latest_siren6_release() -> dict[str, object] | None:
    releases = _fetch_json(f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases")
    if not isinstance(releases, list):
        return None

    for release in releases:
        if not isinstance(release, dict):
            continue
        tag_name = str(release.get("tag_name") or release.get("name") or "").strip()
        if _extract_prefixed_version(tag_name) is not None:
            return release
    return None


def _fetch_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "siren6_helper",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _download_file(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "siren6_helper"})
    with urllib.request.urlopen(request, timeout=60) as response:
        with destination.open("wb") as file:
            shutil.copyfileobj(response, file)


def _asset_download_url(release: dict[str, object]) -> str | None:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None

    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if asset.get("name") == RELEASE_ASSET_NAME:
            return str(asset.get("browser_download_url") or "")
    return None


def _find_extracted_app_dir(extract_dir: Path) -> Path | None:
    preferred = extract_dir / APP_FOLDER_NAME
    if (preferred / EXE_NAME).exists():
        return preferred

    for path in extract_dir.rglob(EXE_NAME):
        return path.parent
    return None


def _write_qt_update_script(source_dir: Path, target_dir: Path, executable: Path) -> Path:
    if sys.platform.startswith("win"):
        script_path = source_dir.parent / "apply_update.ps1"
        script_path.write_text(
            "\n".join(
                [
                    f"$pidToWait = {os.getpid()}",
                    f"$source = '{_powershell_literal(source_dir)}'",
                    f"$target = '{_powershell_literal(target_dir)}'",
                    f"$exe = '{_powershell_literal(executable)}'",
                    "Wait-Process -Id $pidToWait -ErrorAction SilentlyContinue",
                    "Start-Sleep -Milliseconds 500",
                    "Get-ChildItem -LiteralPath $source -Force |",
                    "    Copy-Item -Destination $target -Recurse -Force",
                    "Start-Process -FilePath $exe -WorkingDirectory $target",
                ]
            ),
            encoding="utf-8",
        )
        return script_path

    script_path = source_dir.parent / "apply_update.sh"
    script_path.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 1; done",
                "sleep 1",
                f"cp -R {shlex.quote(str(source_dir))}/* {shlex.quote(str(target_dir))}/",
                f"chmod +x {shlex.quote(str(executable))} 2>/dev/null || true",
                (
                    f"cd {shlex.quote(str(target_dir))} && "
                    f"{shlex.quote(str(executable))} >/dev/null 2>&1 &"
                ),
            ]
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    return script_path


def _extract_prefixed_version(tag: str):
    match = re.fullmatch(rf"{re.escape(RELEASE_TAG_PREFIX)}[_\-.](.+)", (tag or "").strip())
    if not match:
        return None
    return _parse_version(match.group(1))


def _extract_optional_prefixed_version(tag: str):
    tag = (tag or "").strip()
    match = re.fullmatch(rf"{re.escape(RELEASE_TAG_PREFIX)}[_\-.](.+)", tag)
    if match:
        tag = match.group(1)
    return _parse_version(tag)


def _parse_version(tag: str):
    tag = (tag or "").strip()
    if tag.startswith("v."):
        tag = tag[2:]
    elif tag.startswith("v"):
        tag = tag[1:]
    try:
        return version.parse(tag)
    except version.InvalidVersion:
        logger.debug(f"invalid version tag: {tag}")
        return None


def _powershell_literal(path: Path) -> str:
    return str(path).replace("'", "''")


class GitHubUpdater:
    RELEASE_TAG_PREFIX = "siren6"

    def __init__(self, github_author='', github_repo='', zipfile_basename='', current_version='', main_exe_name=None, updator_exe_name=None):
        """
        GitHub自動アップデータの初期化
        
        Args:
            github_repo (str): GitHubリポジトリ（例: "username/repository"）
            current_version (str): 現在のバージョン（例: "1.0.0"）
            main_exe_name (str): メインプログラムのexe名（例: "main.exe"）
            updator_exe_name (str): アップデート用プログラムのexe名 (例: "update.exe"）
        """
        self.github_author = github_author
        self.github_repo = github_repo
        self.zipfile_basename = zipfile_basename
        self.current_version = current_version
        self.main_exe_name = main_exe_name or "main.exe"
        self.updator_exe_name = updator_exe_name or "update.exe"
        self.base_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
        self.temp_dir = self.base_dir / "tmp"
        self.backup_dir = self.base_dir / "backup"
        logger.debug(f"base_dir:{self.base_dir}")
        
        # GUI関連
        self.root = None
        self.progress_var = None
        self.status_var = None
        self.progress_bar = None

    def ico_path(self, relative_path):
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def _extract_version_for_compare(self, tag, require_prefix=False):
        tag = (tag or "").strip()
        if require_prefix:
            match = re.fullmatch(rf"{re.escape(self.RELEASE_TAG_PREFIX)}[_\-.](.+)", tag)
            if not match:
                return None
            tag = match.group(1)
        else:
            match = re.fullmatch(rf"{re.escape(self.RELEASE_TAG_PREFIX)}[_\-.](.+)", tag)
            if match:
                tag = match.group(1)

        if tag.startswith("v."):
            tag = tag[2:]
        elif tag.startswith("v"):
            tag = tag[1:]

        try:
            return version.parse(tag)
        except version.InvalidVersion:
            logger.debug(f"invalid version tag: {tag}")
            return None

    def get_latest_version(self):
        # self.ico=self.ico_path('icon.ico')
        ret = None
        url = f'https://github.com/{self.github_author}/{self.github_repo}/tags'
        r = requests.get(url, timeout=5)
        soup = BeautifulSoup(r.text,features="html.parser")
        for tag in soup.find_all('a'):
            if 'releases/tag/' in tag['href']:
                logger.debug(f"tag = {tag}")
                tag_name = tag['href'].split('/')[-1]
                if self._extract_version_for_compare(tag_name, require_prefix=True) is None:
                    logger.debug(f"skip non-{self.RELEASE_TAG_PREFIX} tag: {tag_name}")
                    continue
                ret = tag_name
                break # 対象タグの中で1番上が最新なので即break
        return ret

    def check_for_updates(self):
        """
        GitHubで最新版をチェック
        
        Returns:
            tuple: (is_update_available, latest_version, download_url)
        """
        logger.debug(f"github_repo:{self.github_author}/{self.github_repo}")
        try:
            latest_version = self.get_latest_version()
            if latest_version is None:
                logger.info(f"{self.RELEASE_TAG_PREFIX} release tag not found")
                return False, None, None
            download_url = f"https://github.com/{self.github_author}/{self.github_repo}/releases/download/{latest_version}/{self.zipfile_basename}.zip"
            logger.debug(f"latest_version:{latest_version}, current:{self.current_version}")
            
            # バージョン比較
            latest_for_compare = self._extract_version_for_compare(latest_version, require_prefix=True)
            current_for_compare = self._extract_version_for_compare(self.current_version)
            if latest_for_compare is None or current_for_compare is None:
                logger.info(f"version parse failed: latest={latest_version}, current={self.current_version}")
                return False, latest_version, None
            if latest_for_compare > current_for_compare:
                return True, latest_version, download_url
            else:
                return False, latest_version, None
                
        except Exception as e:
            print(f"アップデートチェックエラー: {e}")
            return False, None, None
    
    def create_gui(self):
        """アップデート用GUIの作成"""
        import tkinter as tk
        from tkinter import ttk

        self.root = tk.Tk()
        # self.icon = tk.PhotoImage(data=icon.icon_data)
        # self.root.iconphoto(False, self.icon)
        self.root.title("プログラム更新中...")
        self.root.geometry("500x200")
        self.root.resizable(False, False)
        
        # 中央に配置
        self.root.geometry("+%d+%d" % (
            (self.root.winfo_screenwidth() / 2 - 250),
            (self.root.winfo_screenheight() / 2 - 100)
        ))
        
        # メインフレーム
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # タイトル
        title_label = ttk.Label(main_frame, text="プログラムを最新版に更新しています...", 
                               font=("Arial", 12, "bold"))
        title_label.pack(pady=(0, 20))
        
        # ステータステキスト
        self.status_var = tk.StringVar(value="更新確認中...")
        status_label = ttk.Label(main_frame, textvariable=self.status_var)
        status_label.pack(pady=(0, 10))
        
        # プログレスバー
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, 
                                          maximum=100, length=400)
        self.progress_bar.pack(pady=(0, 20))
        
        # キャンセルボタン
        cancel_button = ttk.Button(main_frame, text="キャンセル", 
                                 command=self.cancel_update)
        cancel_button.pack()
        
        self.root.protocol("WM_DELETE_WINDOW", self.cancel_update)
        
    def update_status(self, message, progress=None):
        """ステータス更新"""
        if self.status_var:
            self.status_var.set(message)
        if progress is not None and self.progress_var:
            self.progress_var.set(progress)
        if self.root:
            self.root.update()
    
    def download_file(self, url, filepath):
        """
        ファイルをダウンロード（進行状況表示付き）
        
        Args:
            url (str): ダウンロードURL
            filepath (Path): 保存先パス
        """
        self.update_status("最新版をダウンロード中...", 0)
        
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        block_size = 8192
        downloaded_size = 0
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    
                    if total_size > 0:
                        progress = (downloaded_size / total_size) * 50  # 50%まで
                        self.update_status(f"ダウンロード中... {downloaded_size // 1024}KB / {total_size // 1024}KB", 
                                         progress)
    
    def create_backup(self):
        """現在のファイルをバックアップ"""
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir)
        
        self.backup_dir.mkdir()
        
        # 重要なファイルをバックアップ
        for item in self.base_dir.iterdir():
            if item.name not in ['temp_update', 'backup'] and item.is_file():
                shutil.copy2(item, self.backup_dir)

    def copy_and_skip_errors(self, src, dst):
        # コピー先ディレクトリを作成
        os.makedirs(dst, exist_ok=True)

        for root, dirs, files in os.walk(src):
            # 相対パスを計算して、コピー先の階層を再現
            rel_path = os.path.relpath(root, src)
            dest_dir = os.path.join(dst, rel_path)
            os.makedirs(dest_dir, exist_ok=True)

            for file in files:
                src_file = os.path.join(root, file)
                dst_file = os.path.join(dest_dir, file)
            
                try:
                    # copy2 はメタデータ（作成日時など）も保持して上書きコピー
                    shutil.copy2(src_file, dst_file)
                except (PermissionError, OSError):
                    # 実行中のファイルなどでアクセス拒否された場合はここに来る
                    logger.error(f"スキップ（使用中）: {file}")
                    continue 

    def create_restart_script(self, old_exe_path):
        logger.info('')
        """再起動用スクリプト作成"""
        if sys.platform.startswith('win'):
            script_path = self.base_dir / "restart_update.bat"
            script_content = f"""@echo off
timeout /t 2 /nobreak >nul
:: 2. もし古いプロセスが残っていたら強制終了（念のため）
taskkill /f /im "{self.main_exe_name}" >nul 2>&1

:retry_del
timeout /t 1 /nobreak >nul
if exist "{old_exe_path}" (
    del /f /q "{old_exe_path}" >nul 2>&1
    if exist "{old_exe_path}" (
        echo 削除再試行中...
        goto retry_del
    )
)

start "" "{self.main_exe_name}"
del "%~f0"
"""
            with open(script_path, 'w', encoding='shift_jis') as f:
                f.write(script_content)
            os.chmod(script_path, 0o755)
        
        logger.info(f"path:{script_path}")
        return script_path
    
    def cleanup(self):
        """一時ファイルの清掃"""
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            print(f"清掃エラー: {e}")
    
    def cancel_update(self):
        """アップデートキャンセル"""
        self.cleanup()
        if self.root:
            self.root.destroy()
        sys.exit(0)
    
    def extract_zip_file(self, zip_path):
        """zipファイルを解凍する。tmp直下にそのまま解凍する。

        Args:
            zip_path (str): path of zipfile
        """
        shutil.unpack_archive(zip_path, 'tmp')

    def check_and_update(self):
        """
        メインプログラムから呼び出す関数
        アップデートが必要な場合のみGUIを表示して更新実行
        
        Returns:
            bool: アップデートが実行された場合True
        """
        logger.info('check and update')
        try:
            # アップデート確認（GUIなし）
            is_update_available, latest_version, download_url = self.check_for_updates()
            logger.info(f"available:{is_update_available}, latest:{latest_version}, url:{download_url}")
            
            if is_update_available:
                from tkinter import messagebox

                self.create_gui()
                # 確認ダイアログ
                result = messagebox.askyesno(
                    "アップデート確認",
                    f"新しいバージョン（{latest_version}）が利用可能です。\n"
                    f"現在のバージョン: {self.current_version}\n\n"
                    "今すぐ更新しますか？"
                )
                
                if result:
                    self.cleanup()
                    
                    # 別スレッドで更新実行
                    def update_thread():
                        try:
                            # ダウンロード
                            zip_path = self.temp_dir / f"update_{latest_version}.zip"
                            logger.info(f'zip_path: {zip_path}')
                            self.temp_dir.mkdir(exist_ok=True)
                            
                            logger.info('download')
                            self.download_file(download_url, zip_path)
                            self.extract_zip_file(zip_path)
                            logger.info('replace')
                            old_exe_name = f"old_{self.main_exe_name}"
                            # 実行中のmain fileをリネーム(できるらしい)
                            os.rename(self.main_exe_name, old_exe_name)
                            self.copy_and_skip_errors(self.temp_dir/self.zipfile_basename, Path('.'))
                            
                            # 更新完了後にメインプログラムを再起動するためのバッチファイルを作成
                            self.create_restart_script(old_exe_name)

                            self.update_status("更新完了！プログラムを再起動します...", 100)
                            #self.root.after(2000, self.restart_program)
                            self.restart_program()
                            
                        except Exception as e:
                            logger.error(traceback.format_exc())
                            error_msg = f"更新エラー: {e}"
                            self.root.after(0, lambda: messagebox.showerror("エラー", error_msg))
                            self.root.after(0, self.cancel_update)
                    
                    thread = threading.Thread(target=update_thread, daemon=True)
                    thread.start()
                    
                    self.root.mainloop()
                    return True
                else:
                    # 更新しない場合はGUIを閉じる
                    if self.root:
                        self.root.destroy()
                        self.root = None
                    return False
            else:
                logger.info('no update')
            return False
            
        except Exception as e:
            logger.debug(traceback.format_exc())
            print(f"アップデート確認エラー: {e}")
            return False
    
    def restart_program(self):
        """プログラム再起動"""
        logger.info('retart program')
        script_path = self.base_dir / ("restart_update.bat" if sys.platform.startswith('win') 
                                     else "restart_update.sh")
        if script_path.exists():
            if sys.platform.startswith('win'):
                subprocess.Popen(
                    ["cmd", "/c", str(script_path)],
                    shell=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=subprocess.CREATE_NEW_CONSOLE # 新しいウィンドウで開く（デバッグに便利）
                    )
            else:
                subprocess.Popen(['/bin/bash', str(script_path)])
            
            # if self.root:
                # self.root.destroy()
            sys.exit(0)


def main():
    try:
        with open('version.txt', 'r') as f:
            tmp = f.readline()
            print(tmp)
            SWVER = tmp.strip()[2:] if tmp.startswith('v') else tmp.strip()
    except Exception:
        logger.debug(traceback.format_exc())
        SWVER = "0.0.0"
    #SWVER='1.0.0' # for test

    updater = GitHubUpdater(
        github_author='dj-kata',
        github_repo='siren_helper',
        zipfile_basename='siren6_helper',
        current_version=SWVER,           # 現在のバージョン
        main_exe_name="siren6_helper.exe",  # メインプログラムのexe名
        updator_exe_name="siren6_helper.exe",           # アップデート用プログラムのexe名
    )
    
    # メインプログラムから呼び出す場合
    updater.check_and_update()


if __name__ == "__main__":
    main()
