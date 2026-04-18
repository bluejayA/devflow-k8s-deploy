"""파일 I/O 보안 헬퍼.

- read_text_limited: 파일 크기 상한 검증 후 텍스트 읽기 (DoS 방어)
- is_within: symlink escape 방어용 경로 포함 확인
"""

from pathlib import Path

MAX_FILE_MB = 5


def read_text_limited(
    path: Path,
    max_mb: int = MAX_FILE_MB,
    encoding: str = "utf-8",
) -> str:
    """파일 크기 상한 검증 후 텍스트 읽기. 초과 시 ValueError.

    Args:
        path: 읽을 파일 경로
        max_mb: 최대 허용 크기 (MB). 기본 5.
        encoding: 인코딩. 기본 utf-8.

    Returns:
        파일 내용 문자열.

    Raises:
        ValueError: 파일 크기가 max_mb 초과.
        OSError: 파일 읽기 실패.
        UnicodeDecodeError: 인코딩 변환 실패.
    """
    size_bytes = path.stat().st_size
    if size_bytes > max_mb * 1024 * 1024:
        raise ValueError(
            f"파일이 {max_mb}MB 초과: {path} ({size_bytes} bytes)"
        )
    return path.read_text(encoding=encoding)


def is_within(root: Path, target: Path) -> bool:
    """target을 resolve한 결과가 root.resolve() 하위인지 확인. symlink escape 방어.

    Args:
        root: 기준 디렉토리 경로.
        target: 검사할 파일/디렉토리 경로.

    Returns:
        True이면 target이 root 하위. False이면 escape 또는 외부 경로.
    """
    try:
        root_resolved = root.resolve(strict=False)
        target_resolved = target.resolve(strict=False)
        target_resolved.relative_to(root_resolved)
        return True
    except ValueError:
        return False
