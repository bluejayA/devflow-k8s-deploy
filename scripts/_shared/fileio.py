"""파일 I/O 보안 헬퍼.

- read_text_limited: 파일 크기 상한 검증 후 텍스트 읽기 (DoS 방어)
- is_within: symlink escape 방어용 경로 포함 확인
- check_yaml_refs: YAML anchor/alias 개수 사전 검사 (bomb 방어)
"""

import re
from pathlib import Path

import yaml

MAX_FILE_MB = 5

# YAML bomb 방어: anchor(&) / alias(*) 정규식
_YAML_REF_RE = re.compile(r"[&*][A-Za-z_][\w.-]*")
MAX_YAML_REFS_DEFAULT = 16


def check_yaml_refs(content: str, max_refs: int = MAX_YAML_REFS_DEFAULT) -> None:
    """YAML content의 anchor(&)/alias(*) 개수를 사전 검사.

    max_refs 초과 시 yaml.YAMLError raise (bomb 방어).

    Args:
        content: YAML 원문 문자열
        max_refs: 허용 최대 개수. 기본 16.

    Raises:
        yaml.YAMLError: anchor/alias 개수가 max_refs 초과
    """
    count = len(_YAML_REF_RE.findall(content))
    if count > max_refs:
        raise yaml.YAMLError(
            f"YAML anchor/alias 개수 과다 ({count} > {max_refs}). bomb 방어로 거부."
        )


def read_text_limited(
    path: Path,
    max_mb: int | float = MAX_FILE_MB,
    encoding: str = "utf-8",
) -> str:
    """파일 크기 상한 검증 후 텍스트 읽기. 초과 시 ValueError.

    Args:
        path: 읽을 파일 경로
        max_mb: 최대 허용 크기 (MB). int 또는 float 허용. 기본 5.
        encoding: 인코딩. 기본 utf-8.

    Returns:
        파일 내용 문자열.

    Raises:
        ValueError: 파일 크기가 max_mb 초과.
        OSError: 파일 없음 / 권한 부족 시 stat 단계 또는 read 단계에서 발생.
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
