from __future__ import annotations

import asyncio
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath


class MediaStorage(ABC):
    @abstractmethod
    async def save(self, source: Path, relative_path: str) -> None: ...

    @abstractmethod
    async def delete(self, relative_path: str) -> None: ...

    @abstractmethod
    def get_public_url(self, relative_path: str) -> str: ...

    @abstractmethod
    def exists(self, relative_path: str) -> bool: ...

    @abstractmethod
    async def move(self, source_path: str, target_path: str) -> None: ...


class LocalMediaStorage(MediaStorage):
    def __init__(self, root: Path, public_prefix: str = "/media"):
        self.root = root.resolve()
        self.public_prefix = public_prefix.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative_path: str) -> Path:
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError("Небезопасный путь медиа")
        resolved = (self.root / Path(*pure.parts)).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("Путь медиа выходит за пределы хранилища")
        return resolved

    async def save(self, source: Path, relative_path: str) -> None:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, source, target)

    async def delete(self, relative_path: str) -> None:
        target = self._resolve(relative_path)
        if target.is_dir():
            await asyncio.to_thread(shutil.rmtree, target, True)
        else:
            target.unlink(missing_ok=True)

    def get_public_url(self, relative_path: str) -> str:
        self._resolve(relative_path)
        return f"{self.public_prefix}/{relative_path}"

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path).exists()

    async def move(self, source_path: str, target_path: str) -> None:
        source = self._resolve(source_path)
        target = self._resolve(target_path)
        if target.exists():
            raise FileExistsError(f"Целевой путь уже существует: {target_path}")
        await asyncio.to_thread(os.replace, source, target)

    async def activate_staging(self, staging: str, pack_id: str) -> None:
        source = self._resolve(staging)
        target = self._resolve(pack_id)
        if target.exists():
            raise FileExistsError(f"Каталог пака уже существует: {pack_id}")
        await asyncio.to_thread(os.replace, source, target)
