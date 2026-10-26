"""
Скачивает видео по ссылке с любого поддерживаемого сайта и сохраняет аудио в .mp3.

Работает через yt-dlp, поэтому поддерживает больше тысячи сайтов: YouTube, VK Видео,
Rutube, Дзен, Telegram (публичные каналы), TikTok, Instagram, X/Twitter, Twitch,
OK.ru, Vimeo, Dailymotion, SoundCloud и другие. Полный список: yt-dlp --list-extractors

Зависимости:
    pip install yt-dlp
    + ffmpeg в системе (macOS: brew install ffmpeg)

Использование:
    python download_audio.py <ссылка> [папка] [--bitrate 192] [--cookies-from-browser chrome]
"""

import argparse
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import yt_dlp
except ImportError:
    sys.exit("Не найден yt-dlp. Установи: pip install yt-dlp")


# Домен -> красивое имя сервиса. Нужно только для вывода, скачивает yt-dlp сам.
SERVICES = {
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    "vk.com": "VK Видео", "vkvideo.ru": "VK Видео", "vk.ru": "VK Видео",
    "rutube.ru": "Rutube",
    "dzen.ru": "Дзен",
    "t.me": "Telegram",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "x.com": "X (Twitter)", "twitter.com": "X (Twitter)",
    "twitch.tv": "Twitch",
    "ok.ru": "Одноклассники",
    "vimeo.com": "Vimeo",
    "dailymotion.com": "Dailymotion",
    "soundcloud.com": "SoundCloud",
    "reddit.com": "Reddit",
    "facebook.com": "Facebook", "fb.watch": "Facebook",
    "music.yandex.ru": "Яндекс Музыка",
}


class DownloadFailed(Exception):
    pass


def detect_service(url: str) -> str:
    """Определяет сервис по домену ссылки (m.vk.com, www.youtube.com и т.п. тоже узнаются)."""
    host = (urlparse(url).hostname or "").lower()
    for domain, name in SERVICES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or "неизвестный сайт"


BROWSERS = ("chrome", "safari", "firefox", "edge", "brave", "opera", "vivaldi", "chromium", "whale")


def parse_browser(value: str) -> tuple:
    """'chrome' или 'chrome:Profile 1' -> кортеж, который ждёт yt-dlp: (браузер, профиль, keyring, контейнер)."""
    name, _, profile = value.partition(":")
    name = name.strip().lower()
    if name not in BROWSERS:
        raise DownloadFailed(
            f"Браузер '{name}' не поддерживается. Доступны: {', '.join(BROWSERS)}. "
            "Для Яндекс Браузера, Arc и других используй --cookies с файлом cookies.txt"
        )
    return (name, profile.strip() or None, None, None)


def download_audio(
    url: str,
    out_dir: Path,
    bitrate: int = 192,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
) -> Path:
    """Скачивает аудио по ссылке и возвращает путь к готовому .mp3."""
    if shutil.which("ffmpeg") is None:
        raise DownloadFailed("Не найден ffmpeg. Он нужен для конвертации в mp3 (macOS: brew install ffmpeg)")

    out_dir.mkdir(parents=True, exist_ok=True)

    options = {
        # Лучшая аудиодорожка; если сайт отдаёт только склеенное видео со звуком, берём его
        "format": "bestaudio/best",
        # id в имени защищает от перезаписи, если у двух видео одинаковые названия
        "outtmpl": str(out_dir / "%(title).120B [%(id)s].%(ext)s"),
        "windowsfilenames": True,  # убирает из названия символы, запрещённые в именах файлов
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(bitrate),
            }
        ],
        "noplaylist": True,
        "quiet": False,
    }
    # Некоторые сайты (VK, Instagram, закрытые видео) отдают видео только залогиненным.
    # yt-dlp может взять cookies из браузера, где ты уже вошёл в аккаунт.
    if cookies_from_browser:
        options["cookiesfrombrowser"] = parse_browser(cookies_from_browser)
    # Запасной путь для браузеров, которые yt-dlp не умеет читать (Яндекс, Arc):
    # cookies выгружаются расширением в файл формата Netscape (cookies.txt)
    if cookies_file:
        if not Path(cookies_file).is_file():
            raise DownloadFailed(f"Файл cookies не найден: {cookies_file}")
        options["cookiefile"] = str(cookies_file)

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadFailed(str(e)) from e

    # После постпроцессинга yt-dlp записывает путь к итоговому файлу сюда
    downloads = info.get("requested_downloads") or []
    if downloads and downloads[0].get("filepath"):
        return Path(downloads[0]["filepath"])
    # Запасной вариант: имя по шаблону, расширение mp3
    return Path(yt_dlp.YoutubeDL(options).prepare_filename(info)).with_suffix(".mp3")


def main() -> None:
    parser = argparse.ArgumentParser(description="Видео по ссылке -> mp3")
    parser.add_argument("url", help="ссылка на видео")
    parser.add_argument("out_dir", nargs="?", default="downloads", help="папка для сохранения (по умолчанию downloads)")
    parser.add_argument("--bitrate", type=int, default=192, help="битрейт mp3 в kbps (128, 192, 320)")
    parser.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER",
        help="взять cookies из браузера, если видео требует входа: " + ", ".join(BROWSERS) + " (профиль: chrome:'Profile 1')",
    )
    parser.add_argument("--cookies", type=Path, metavar="FILE", help="файл cookies.txt (для Яндекс Браузера, Arc и т.п.)")
    args = parser.parse_args()

    print(f"Сервис: {detect_service(args.url)}")
    try:
        mp3 = download_audio(args.url, Path(args.out_dir), args.bitrate, args.cookies_from_browser, args.cookies)
    except DownloadFailed as e:
        sys.exit(f"Ошибка скачивания: {e}")
    print(f"\nГотово: {mp3}")


if __name__ == "__main__":
    main()
