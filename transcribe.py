"""
Транскрибация аудио через Whisper на Apple Silicon (mlx-whisper, вычисления на GPU через MLX).

Зависимости:
    pip install mlx-whisper
    brew install ffmpeg        # whisper декодирует аудио через ffmpeg

Использование:
    python transcribe.py audio.mp3
    python transcribe.py audio.mp3 --model medium --lang ru --formats txt srt
    python transcribe.py audio.mp3 --lang auto       # автоопределение языка

Модель скачивается с Hugging Face при первом запуске и кешируется (~/.cache/huggingface).
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

# Короткие имена -> репозитории с весами, сконвертированными под MLX
MODELS = {
    "turbo": "mlx-community/whisper-large-v3-turbo",   # почти как large-v3, но в разы быстрее
    "large": "mlx-community/whisper-large-v3-mlx",     # максимальная точность
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "base": "mlx-community/whisper-base-mlx",
}


class TranscribeFailed(Exception):
    pass


def format_timestamp(seconds: float) -> str:
    """Секунды -> 'ЧЧ:ММ:СС,мс' (формат SRT)."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_txt(result: dict, path: Path) -> None:
    # Каждый сегмент с новой строки читается легче, чем одна сплошная простыня
    lines = [seg["text"].strip() for seg in result["segments"]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_srt(result: dict, path: Path) -> None:
    blocks = []
    for i, seg in enumerate(result["segments"], start=1):
        blocks.append(
            f"{i}\n{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}\n{seg['text'].strip()}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")


WRITERS = {"txt": write_txt, "srt": write_srt}


def transcribe(
    audio: Path,
    model: str = "turbo",
    lang: str | None = "ru",
    out_dir: Path | None = None,
    formats: list[str] = ("txt", "srt"),
) -> list[Path]:
    """Распознаёт речь в файле и возвращает пути к сохранённым файлам."""
    # Импорт внутри функции: так download_audio.py и link2text.py запускаются и без mlx,
    # а понятная ошибка появляется только когда дело дошло до распознавания
    try:
        import mlx_whisper
    except ImportError:
        raise TranscribeFailed("Не найден mlx-whisper. Установи: pip install mlx-whisper (только Apple Silicon)")

    if shutil.which("ffmpeg") is None:
        raise TranscribeFailed("Не найден ffmpeg. Установи: brew install ffmpeg")
    if not audio.is_file():
        raise TranscribeFailed(f"Файл не найден: {audio}")

    print(f"Модель: {MODELS[model]}")
    print(f"Файл:   {audio}")
    start = time.perf_counter()

    result = mlx_whisper.transcribe(
        str(audio),
        path_or_hf_repo=MODELS[model],
        language=lang,          # None = автоопределение; явный язык надёжнее и чуть быстрее
        verbose=False,          # True печатает сегменты по ходу работы
        # Не даём модели опираться на предыдущий текст: меньше "залипаний" и повторов на длинных записях
        condition_on_previous_text=False,
    )

    elapsed = time.perf_counter() - start
    out_dir = out_dir or audio.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for fmt in formats:
        out_path = out_dir / f"{audio.stem}.{fmt}"
        WRITERS[fmt](result, out_path)
        saved.append(out_path)
        print(f"Сохранено: {out_path}")

    duration = result["segments"][-1]["end"] if result["segments"] else 0
    speed = f", x{duration / elapsed:.1f} от реального времени" if elapsed > 0 and duration else ""
    print(f"Язык: {result.get('language')}. Время: {elapsed:.1f} с{speed}")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Транскрибация аудио через mlx-whisper")
    parser.add_argument("audio", type=Path, help="путь к аудиофайлу (.mp3, .m4a, .wav, ...)")
    parser.add_argument("--model", choices=MODELS, default="turbo", help="размер модели (по умолчанию turbo)")
    parser.add_argument("--lang", default="ru", help="код языка (ru, en, ...) или auto")
    parser.add_argument("--out", type=Path, default=None, help="папка для результата (по умолчанию рядом с аудио)")
    parser.add_argument("--formats", nargs="+", choices=WRITERS, default=["txt", "srt"], help="форматы вывода")
    args = parser.parse_args()

    lang = None if args.lang == "auto" else args.lang
    try:
        transcribe(args.audio, args.model, lang, args.out, args.formats)
    except TranscribeFailed as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
