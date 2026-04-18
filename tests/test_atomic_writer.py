"""Unit tests for AtomicWriter — TDD 선행 작성.

Tests:
 1.  기본 흐름 (output_dir 없음 + commit): staging_dir에 쓴 파일이 output_dir로 이동
 2.  commit 없이 __exit__: staging_dir 정리, output_dir 미생성
 3.  예외 발생 시 cleanup: staging_dir 삭제, output_dir 이전 상태 유지
 4.  on_exists='overwrite': 기존 output_dir 삭제 후 rename
 5.  on_exists='suffix': output_dir-YYYY-MM-DDTHH-MM/ 형태로 rename
 6.  on_exists='prompt' + "덮어쓰기": overwrite 동작
 7.  on_exists='prompt' + "suffix로 새 디렉토리 만들기": suffix 동작
 8.  on_exists='prompt' + "취소": OutputExistsAbort, staging_dir 정리
 9.  on_exists='prompt' + callback=None: commit 시 OutputExistsAbort
10.  signal handler 등록 + 복구 (SIGINT)
11.  _signal_handler 직접 호출 → cleanup + sys.exit(130)
12.  고아 GC — 7일 이상 .tmp-* 삭제
13.  고아 GC — 7일 미만 .tmp-* 보존
14.  staging_dir은 output_dir.parent 하위 (sibling)
15.  인스턴스마다 고유 uuid staging_dir
16.  PromptRequest 구조 검증 (kind/ko_text/options/help_term_id)
"""

from __future__ import annotations

import os
import re
import signal
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts._shared.errors import OutputExistsAbort
from scripts._shared.types import PromptRequest  # noqa: TCH001
from scripts.atomic_writer import AtomicWriter

# ─── Test 1: 기본 흐름 ───────────────────────────────────────────────────────


def test_basic_commit_moves_staging_to_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"

    with AtomicWriter(output_dir, on_exists="overwrite") as aw:
        (aw.staging_dir / "hello.txt").write_text("hello")
        final = aw.commit()

    assert output_dir.exists()
    assert final == output_dir
    assert (output_dir / "hello.txt").read_text() == "hello"
    # staging_dir은 사라져야 함
    assert not aw.staging_dir.exists()


# ─── Test 2: commit 없이 __exit__ ────────────────────────────────────────────


def test_no_commit_cleans_up_staging(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"

    with AtomicWriter(output_dir, on_exists="overwrite") as aw:
        staging = aw.staging_dir
        (staging / "data.txt").write_text("data")
        # commit 호출 안 함

    assert not staging.exists(), "staging_dir이 정리되어야 함"
    assert not output_dir.exists(), "output_dir은 생성되지 않아야 함"


# ─── Test 3: 예외 발생 시 cleanup ────────────────────────────────────────────


def test_exception_cleans_up_staging(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    staging_ref: Path | None = None

    with pytest.raises(RuntimeError):
        with AtomicWriter(output_dir, on_exists="overwrite") as aw:
            staging_ref = aw.staging_dir
            raise RuntimeError("something went wrong")

    assert staging_ref is not None
    assert not staging_ref.exists(), "staging_dir이 정리되어야 함"
    assert not output_dir.exists(), "output_dir은 이전 상태 유지 (없음)"


def test_exception_preserves_existing_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "existing.txt").write_text("original")

    with pytest.raises(ValueError):
        with AtomicWriter(output_dir, on_exists="overwrite"):
            raise ValueError("abort")

    # 기존 output_dir 내용 보존
    assert output_dir.exists()
    assert (output_dir / "existing.txt").read_text() == "original"


# ─── Test 4: on_exists='overwrite' ───────────────────────────────────────────


def test_overwrite_replaces_existing_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("old content")

    with AtomicWriter(output_dir, on_exists="overwrite") as aw:
        (aw.staging_dir / "new.txt").write_text("new content")
        final = aw.commit()

    assert final == output_dir
    assert (output_dir / "new.txt").read_text() == "new content"
    assert not (output_dir / "old.txt").exists(), "기존 파일은 삭제되어야 함"


# ─── Test 5: on_exists='suffix' ──────────────────────────────────────────────


def test_suffix_creates_timestamped_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("old")

    with AtomicWriter(output_dir, on_exists="suffix") as aw:
        (aw.staging_dir / "new.txt").write_text("new")
        final = aw.commit()

    # suffix 형식: output-YYYY-MM-DDTHH-MM
    suffix_pattern = re.compile(r"^output-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}$")
    assert suffix_pattern.match(final.name), f"suffix 형식이 틀림: {final.name}"
    assert (final / "new.txt").read_text() == "new"
    # 원본 output_dir은 그대로
    assert output_dir.exists()
    assert (output_dir / "old.txt").exists()


# ─── Test 6: on_exists='prompt' + "덮어쓰기" ─────────────────────────────────


def test_prompt_overwrite_callback(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("old")

    callback = MagicMock(return_value="덮어쓰기")

    with AtomicWriter(output_dir, on_exists="prompt", prompt_callback=callback) as aw:
        (aw.staging_dir / "new.txt").write_text("new")
        final = aw.commit()

    callback.assert_called_once()
    assert final == output_dir
    assert (output_dir / "new.txt").read_text() == "new"
    assert not (output_dir / "old.txt").exists()


# ─── Test 7: on_exists='prompt' + "suffix로 새 디렉토리 만들기" ─────────────────


def test_prompt_suffix_callback(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    callback = MagicMock(return_value="suffix로 새 디렉토리 만들기")

    with AtomicWriter(output_dir, on_exists="prompt", prompt_callback=callback) as aw:
        (aw.staging_dir / "data.txt").write_text("data")
        final = aw.commit()

    suffix_pattern = re.compile(r"^output-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}$")
    assert suffix_pattern.match(final.name), f"suffix 형식이 틀림: {final.name}"
    callback.assert_called_once()


# ─── Test 8: on_exists='prompt' + "취소" ─────────────────────────────────────


def test_prompt_cancel_raises_output_exists_abort(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "keep.txt").write_text("keep")

    callback = MagicMock(return_value="취소")
    staging_ref: Path | None = None

    with pytest.raises(OutputExistsAbort):
        with AtomicWriter(output_dir, on_exists="prompt", prompt_callback=callback) as aw:
            staging_ref = aw.staging_dir
            aw.commit()

    assert staging_ref is not None
    assert not staging_ref.exists(), "staging_dir이 정리되어야 함"
    # output_dir 원본 보존
    assert output_dir.exists()
    assert (output_dir / "keep.txt").read_text() == "keep"


# ─── Test 9: on_exists='prompt' + callback=None ──────────────────────────────


def test_prompt_no_callback_raises_output_exists_abort(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with pytest.raises(OutputExistsAbort):
        with AtomicWriter(output_dir, on_exists="prompt", prompt_callback=None) as aw:
            aw.commit()


# ─── Test 10: signal handler 등록 + 복구 (SIGINT) ────────────────────────────


def test_signal_handler_registered_and_restored(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    with AtomicWriter(output_dir, on_exists="overwrite") as aw:
        in_ctx_sigint = signal.getsignal(signal.SIGINT)
        in_ctx_sigterm = signal.getsignal(signal.SIGTERM)

        # context 내부에서 핸들러가 변경되어야 함
        assert in_ctx_sigint is not original_sigint, "SIGINT 핸들러가 등록되어야 함"
        assert in_ctx_sigterm is not original_sigterm, "SIGTERM 핸들러가 등록되어야 함"

        aw.commit()

    # context 탈출 후 이전 핸들러로 복구
    restored_sigint = signal.getsignal(signal.SIGINT)
    restored_sigterm = signal.getsignal(signal.SIGTERM)
    assert restored_sigint is original_sigint, "SIGINT 핸들러가 복구되어야 함"
    assert restored_sigterm is original_sigterm, "SIGTERM 핸들러가 복구되어야 함"


# ─── Test 11: _signal_handler 직접 호출 → cleanup + sys.exit(130) ────────────


def test_signal_handler_calls_cleanup_and_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "output"
    exit_calls: list[int] = []

    monkeypatch.setattr(sys, "exit", lambda code: exit_calls.append(code))

    with AtomicWriter(output_dir, on_exists="overwrite") as aw:
        staging = aw.staging_dir
        (staging / "data.txt").write_text("data")

        aw._signal_handler(signal.SIGTERM, None)

    assert exit_calls == [130], f"sys.exit(130)이 호출되어야 함, 실제: {exit_calls}"
    assert not staging.exists(), "staging_dir이 정리되어야 함"


# ─── Test 12: 고아 GC — 7일 이상 .tmp-* 삭제 ─────────────────────────────────


def test_gc_removes_orphan_older_than_7_days(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    orphan = tmp_path / ".tmp-orphan_old"
    orphan.mkdir()
    (orphan / "file.txt").write_text("old")

    # mtime을 8일 전으로 설정
    eight_days_ago = time.time() - (8 * 24 * 3600)
    os.utime(orphan, (eight_days_ago, eight_days_ago))

    with AtomicWriter(output_dir, on_exists="overwrite") as aw:
        aw.commit()

    assert not orphan.exists(), "7일 이상 고아 디렉토리는 삭제되어야 함"


# ─── Test 13: 고아 GC — 7일 미만 .tmp-* 보존 ─────────────────────────────────


def test_gc_preserves_recent_orphan(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    recent = tmp_path / ".tmp-orphan_recent"
    recent.mkdir()
    (recent / "file.txt").write_text("recent")
    # mtime은 현재 시각 (기본)

    with AtomicWriter(output_dir, on_exists="overwrite") as aw:
        aw.commit()

    assert recent.exists(), "7일 미만 고아 디렉토리는 보존되어야 함"


# ─── Test 14: staging_dir은 output_dir.parent 하위 ───────────────────────────


def test_staging_dir_is_sibling_of_output_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"

    with AtomicWriter(output_dir, on_exists="overwrite") as aw:
        # staging_dir의 parent == output_dir.parent
        assert aw.staging_dir.parent == output_dir.parent, (
            f"staging_dir의 parent가 output_dir.parent와 달라야 함. "
            f"staging_dir.parent={aw.staging_dir.parent}, output_dir.parent={output_dir.parent}"
        )
        # staging_dir 이름이 .tmp-로 시작
        assert aw.staging_dir.name.startswith(".tmp-"), (
            f"staging_dir 이름이 .tmp-로 시작해야 함: {aw.staging_dir.name}"
        )
        aw.commit()


# ─── Test 15: 인스턴스마다 고유 uuid staging_dir ─────────────────────────────


def test_each_instance_has_unique_staging_dir(tmp_path: Path) -> None:
    output1 = tmp_path / "output1"
    output2 = tmp_path / "output2"

    aw1 = AtomicWriter(output1, on_exists="overwrite")
    aw2 = AtomicWriter(output2, on_exists="overwrite")

    try:
        aw1.__enter__()
        aw2.__enter__()

        assert aw1.staging_dir != aw2.staging_dir, "두 인스턴스의 staging_dir은 달라야 함"
    finally:
        aw1.__exit__(None, None, None)
        aw2.__exit__(None, None, None)


# ─── Test 16: PromptRequest 구조 검증 ────────────────────────────────────────


def test_prompt_callback_receives_correct_prompt_request(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    received_requests: list[PromptRequest] = []

    def capturing_callback(req: PromptRequest) -> str:
        received_requests.append(req)
        return "덮어쓰기"

    with AtomicWriter(output_dir, on_exists="prompt", prompt_callback=capturing_callback) as aw:
        aw.commit()

    assert len(received_requests) == 1
    req = received_requests[0]
    assert req.kind == "confirm"
    assert str(output_dir) in req.ko_text
    assert req.options is not None
    assert len(req.options) == 3
    assert "덮어쓰기" in req.options
    assert "취소" in req.options
    assert "suffix로 새 디렉토리 만들기" in req.options
    assert req.help_term_id == "output_dir"
