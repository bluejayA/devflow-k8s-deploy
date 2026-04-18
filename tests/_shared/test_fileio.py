"""fileio.py 단위 테스트.

- read_text_limited: 정상 읽기 / 크기 초과 / 인코딩 에러
- is_within: symlink escape 방어 / 정상 하위 / 외부 경로
"""

import os
from pathlib import Path

import pytest


class TestReadTextLimited:
    def test_normal_read(self, tmp_path: Path) -> None:
        """정상 크기 파일 → 내용 반환."""
        from scripts._shared.fileio import read_text_limited

        f = tmp_path / "hello.txt"
        f.write_text("안녕하세요", encoding="utf-8")

        content = read_text_limited(f)
        assert content == "안녕하세요"

    def test_size_exceeded_raises_value_error(self, tmp_path: Path) -> None:
        """파일 크기가 max_mb 초과 → ValueError."""
        from scripts._shared.fileio import read_text_limited

        big_file = tmp_path / "big.txt"
        # 1MB + 1 byte 파일 생성
        big_file.write_bytes(b"x" * (1 * 1024 * 1024 + 1))

        with pytest.raises(ValueError, match="1MB 초과"):
            read_text_limited(big_file, max_mb=1)

    def test_exact_limit_is_allowed(self, tmp_path: Path) -> None:
        """파일 크기 == max_mb 정확히 동일 → 허용."""
        from scripts._shared.fileio import read_text_limited

        limit_file = tmp_path / "limit.bin"
        limit_file.write_bytes(b"a" * (1 * 1024 * 1024))  # 정확히 1MB

        # 예외 없이 읽혀야 함
        content = read_text_limited(limit_file, max_mb=1, encoding="latin-1")
        assert len(content) == 1 * 1024 * 1024

    def test_unicode_decode_error_propagates(self, tmp_path: Path) -> None:
        """UTF-8 불가 파일을 UTF-8로 읽기 → UnicodeDecodeError."""
        from scripts._shared.fileio import read_text_limited

        bad_file = tmp_path / "bad.txt"
        bad_file.write_bytes(b"\xff\xfe")  # UTF-8로 디코딩 불가

        with pytest.raises(UnicodeDecodeError):
            read_text_limited(bad_file, encoding="utf-8")

    def test_iso8859_encoding(self, tmp_path: Path) -> None:
        """ISO-8859-1 인코딩 파일 → encoding 인자로 정상 읽기 (café 전체 포함)."""
        from scripts._shared.fileio import read_text_limited

        f = tmp_path / "latin.txt"
        f.write_bytes("café".encode("iso-8859-1"))

        content = read_text_limited(f, encoding="iso-8859-1")
        assert "café" in content

    def test_max_mb_accepts_float(self, tmp_path: Path) -> None:
        """max_mb에 float 값(0.5) 전달 → 정상 동작."""
        from scripts._shared.fileio import read_text_limited

        f = tmp_path / "small.txt"
        f.write_text("hello", encoding="utf-8")

        content = read_text_limited(f, max_mb=0.5)
        assert content == "hello"


class TestIsWithin:
    def test_normal_child_path(self, tmp_path: Path) -> None:
        """/tmp/foo/bar → /tmp/foo 하위 → True."""
        from scripts._shared.fileio import is_within

        child = tmp_path / "subdir" / "file.txt"
        child.parent.mkdir(parents=True)
        child.touch()

        assert is_within(tmp_path, child) is True

    def test_outside_path_returns_false(self, tmp_path: Path) -> None:
        """/etc/passwd → tmp_path 하위 아님 → False."""
        from scripts._shared.fileio import is_within

        assert is_within(tmp_path, Path("/etc/passwd")) is False

    def test_symlink_escape_returns_false(self, tmp_path: Path) -> None:
        """symlink → /etc/passwd 연결 → is_within False."""
        from scripts._shared.fileio import is_within

        link = tmp_path / "application.yml"
        try:
            os.symlink("/etc/passwd", link)
        except PermissionError:
            pytest.skip("symlink 생성 권한 없음")

        assert is_within(tmp_path, link) is False

    def test_same_path_is_within(self, tmp_path: Path) -> None:
        """root와 target이 동일 경로 → True."""
        from scripts._shared.fileio import is_within

        assert is_within(tmp_path, tmp_path) is True

    def test_internal_symlink_is_within(self, tmp_path: Path) -> None:
        """root 내부 파일에 대한 symlink → is_within True (내부 symlink 정상 케이스)."""
        import os

        from scripts._shared.fileio import is_within

        real_file = tmp_path / "real.txt"
        real_file.write_text("content", encoding="utf-8")

        link = tmp_path / "link.txt"
        try:
            os.symlink(real_file, link)
        except PermissionError:
            pytest.skip("symlink 생성 권한 없음")

        assert is_within(tmp_path, link) is True
