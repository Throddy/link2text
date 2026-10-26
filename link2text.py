"""
Видео -> текст. Работает и со ссылками, и с файлами на диске.

Три способа:
    1. Положи видео/аудио рядом со скриптом и запусти:  python link2text.py
       Скрипт найдёт все медиафайлы в своей папке и расшифрует те, что ещё не расшифрованы.
    2. Вставляй ссылки или перетаскивай файлы в окно терминала в интерактивном режиме.
    3. Передай всё аргументами:
       python link2text.py https://youtu.be/... lecture.mp4 ~/Downloads/записи/

Ссылки: сервис (YouTube, VK, Rutube, Telegram, TikTok, ...) определяется сам,
аудио скачивается через yt-dlp. Локальные файлы подаются в Whisper напрямую,
ffmpeg сам достаёт звук из видео, отдельно конвертировать не нужно.

Результат для каждого видео: output/<название>/<название>.txt и .srt
"""

import argparse
import re
import sys
from pathlib import Path

from download_audio import BROWSERS, DownloadFailed, detect_service, download_audio
from transcribe import MODELS, WRITERS, TranscribeFailed, transcribe

SCRIPT_DIR = Path(__file__).resolve().parent

# Всё, что умеет читать ffmpeg и что обычно попадается под руку
MEDIA_EXTS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".ts",
    ".mp3", ".m4a", ".wav", ".ogg", ".oga", ".opus", ".flac", ".aac", ".wma",
}


def is_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


def clean_path(text: str) -> str:
    """Чистит путь, вставленный перетаскиванием файла в Терминал.

    macOS Terminal экранирует пробелы и спецсимволы обратным слешем (My\\ Video.mp4),
    а iTerm и другие иногда оборачивают путь в кавычки.
    """
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return re.sub(r"\\(.)", r"\1", text)


def find_media(folder: Path) -> list[Path]:
    """Медиафайлы в папке (без подпапок), отсортированные по имени."""
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS and not p.name.startswith(".")
    )


def already_done(path: Path, args: argparse.Namespace) -> bool:
    return (args.out / path.stem / f"{path.stem}.{args.formats[0]}").exists()


def run_whisper(media: Path, target_dir: Path, args: argparse.Namespace) -> bool:
    lang = None if args.lang == "auto" else args.lang
    try:
        saved = transcribe(media, args.model, lang, target_dir, args.formats)
    except TranscribeFailed as e:
        print(f"Не удалось распознать: {e}")
        return False
    print(f"\nГотово! Папка с результатом: {target_dir}")
    for path in saved:
        print(f"  {path.name}")
    return True


def process_file(path: Path, args: argparse.Namespace) -> bool:
    """Локальный файл: сразу в Whisper, исходник не трогаем."""
    print(f"\n=== Файл: {path.name} ===")
    target_dir = args.out / path.stem
    return run_whisper(path, target_dir, args)


def process_url(url: str, args: argparse.Namespace) -> bool:
    """Ссылка: скачать аудио, затем распознать."""
    print(f"\n=== {detect_service(url)} ===")

    # Скачиваем во временную подпапку, потом переносим в папку с названием видео
    tmp_dir = args.out / "_downloading"
    try:
        mp3 = download_audio(url, tmp_dir, args.bitrate, args.cookies_from_browser, args.cookies)
    except DownloadFailed as e:
        print(f"Не удалось скачать: {e}")
        if any(word in str(e).lower() for word in ("login", "sign in", "cookies", "private")):
            print("Похоже, видео требует входа. Добавь --cookies-from-browser <браузер>, подробности в README")
        return False

    target_dir = args.out / mp3.stem
    target_dir.mkdir(parents=True, exist_ok=True)
    final_mp3 = target_dir / mp3.name
    mp3.replace(final_mp3)

    ok = run_whisper(final_mp3, target_dir, args)
    if ok and args.delete_audio:
        final_mp3.unlink(missing_ok=True)
    elif not ok:
        print(f"Аудио сохранено: {final_mp3}")
    return ok


def process(item: str, args: argparse.Namespace) -> bool:
    """Определяет, что пришло: ссылка, файл или папка."""
    item = item.strip()
    if is_url(item):
        return process_url(item, args)

    path = Path(clean_path(item)).expanduser()
    if path.is_dir():
        files = find_media(path)
        if not files:
            print(f"В папке {path} нет видео или аудио")
            return False
        return all([process_file(f, args) for f in files])
    if path.is_file():
        return process_file(path, args)

    print(f"Не понял, что это: {item}\nНужна ссылка вида https://... или путь к файлу")
    return False


def process_neighbors(args: argparse.Namespace) -> None:
    """Расшифровывает медиафайлы, лежащие рядом со скриптом (и в текущей папке, если она другая)."""
    folders = {SCRIPT_DIR, Path.cwd().resolve()}
    files = sorted({f for folder in folders for f in find_media(folder)})
    todo = [f for f in files if args.force or not already_done(f, args)]

    skipped = len(files) - len(todo)
    if skipped:
        print(f"Пропускаю уже расшифрованные: {skipped} (запусти с --force, чтобы переделать)")
    if not todo:
        return

    print(f"Нашёл файлы рядом со скриптом ({len(todo)}):")
    for f in todo:
        print(f"  {f.name}")
    for f in todo:
        process_file(f, args)


def interactive(args: argparse.Namespace) -> None:
    print("\nВставь ссылку или перетащи файл в это окно и нажми Enter.")
    print("Пустая строка или Ctrl+C завершают работу.")
    while True:
        try:
            item = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not item:
            break
        process(item, args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Видео по ссылке или из файла -> транскрипция")
    parser.add_argument("items", nargs="*", help="ссылки, файлы или папки (без аргументов: файлы рядом со скриптом + интерактивный режим)")
    parser.add_argument("--out", type=Path, default=SCRIPT_DIR / "output", help="папка для результатов (по умолчанию output рядом со скриптом)")
    parser.add_argument("--model", choices=MODELS, default="turbo", help="модель Whisper (по умолчанию turbo)")
    parser.add_argument("--lang", default="ru", help="код языка (ru, en, ...) или auto")
    parser.add_argument("--formats", nargs="+", choices=WRITERS, default=["txt", "srt"], help="форматы вывода")
    parser.add_argument("--bitrate", type=int, default=128, help="битрейт mp3 для ссылок; для распознавания 128 хватает")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER", help="cookies из браузера: " + ", ".join(BROWSERS))
    parser.add_argument("--cookies", type=Path, metavar="FILE", help="файл cookies.txt (Яндекс Браузер, Arc и т.п.)")
    parser.add_argument("--delete-audio", action="store_true", help="удалить скачанный mp3 после транскрибации")
    parser.add_argument("--force", action="store_true", help="расшифровать заново даже то, что уже готово")
    args = parser.parse_args()

    if args.items:
        failed = sum(not process(item, args) for item in args.items)
        sys.exit(1 if failed else 0)

    process_neighbors(args)
    interactive(args)


if __name__ == "__main__":
    main()
