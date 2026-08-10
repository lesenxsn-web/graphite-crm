from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


class StorageError(RuntimeError):
    """Raised when persistent storage cannot be read or written."""


@dataclass(frozen=True)
class GitHubConfig:
    owner: str
    repo: str
    token: str
    branch: str = "main"

    @property
    def enabled(self) -> bool:
        return bool(self.owner and self.repo and self.token)


class JsonStore:
    """Small JSON datastore with local and GitHub Contents API backends.

    GitHub mode is appropriate for a single user or a small team with light
    write traffic. It is not a replacement for a transactional database.
    """

    def __init__(
        self,
        data_dir: str | Path = "data",
        github: GitHubConfig | None = None,
        timeout_seconds: int = 20,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.github = github
        self.timeout_seconds = timeout_seconds

    @property
    def mode(self) -> str:
        return "github" if self.github and self.github.enabled else "local"

    def load(self, collection: str) -> list[dict[str, Any]]:
        if self.mode == "github":
            return self._github_load(collection)
        return self._local_load(collection)

    def save(self, collection: str, rows: list[dict[str, Any]], message: str | None = None) -> None:
        if not isinstance(rows, list):
            raise TypeError("rows must be a list")
        if self.mode == "github":
            self._github_save(collection, rows, message)
        else:
            self._local_save(collection, rows)

    def _path(self, collection: str) -> Path:
        safe = collection.replace("/", "_").replace("..", "_")
        return self.data_dir / f"{safe}.json"

    def _local_load(self, collection: str) -> list[dict[str, Any]]:
        path = self._path(collection)
        if not path.exists():
            return []
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"读取本地数据失败：{path}") from exc
        if not isinstance(content, list):
            raise StorageError(f"数据文件必须是JSON数组：{path}")
        return content

    def _local_save(self, collection: str, rows: list[dict[str, Any]]) -> None:
        path = self._path(collection)
        payload = json.dumps(rows, ensure_ascii=False, indent=2)
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
            ) as temp:
                temp.write(payload)
                temp_path = Path(temp.name)
            os.replace(temp_path, path)
        except OSError as exc:
            raise StorageError(f"写入本地数据失败：{path}") from exc

    def _headers(self) -> dict[str, str]:
        assert self.github is not None
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.github.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _url(self, collection: str) -> str:
        assert self.github is not None
        path = f"data/{collection}.json"
        return f"https://api.github.com/repos/{self.github.owner}/{self.github.repo}/contents/{path}"

    def _github_get(self, collection: str) -> tuple[list[dict[str, Any]], str | None]:
        assert self.github is not None
        response = requests.get(
            self._url(collection),
            headers=self._headers(),
            params={"ref": self.github.branch},
            timeout=self.timeout_seconds,
        )
        if response.status_code == 404:
            return [], None
        if not response.ok:
            raise StorageError(
                f"GitHub读取失败：HTTP {response.status_code}，{response.text[:300]}"
            )
        body = response.json()
        try:
            decoded = base64.b64decode(body["content"]).decode("utf-8")
            rows = json.loads(decoded)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise StorageError("GitHub数据文件内容无法解析") from exc
        if not isinstance(rows, list):
            raise StorageError("GitHub数据文件必须是JSON数组")
        return rows, body.get("sha")

    def _github_load(self, collection: str) -> list[dict[str, Any]]:
        rows, _ = self._github_get(collection)
        return rows

    def _github_save(
        self,
        collection: str,
        rows: list[dict[str, Any]],
        message: str | None,
    ) -> None:
        assert self.github is not None
        _, sha = self._github_get(collection)
        encoded = base64.b64encode(
            json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("ascii")
        payload: dict[str, Any] = {
            "message": message or f"更新CRM数据：{collection}",
            "content": encoded,
            "branch": self.github.branch,
        }
        if sha:
            payload["sha"] = sha
        response = requests.put(
            self._url(collection),
            headers=self._headers(),
            json=payload,
            timeout=self.timeout_seconds,
        )
        if response.status_code == 409:
            raise StorageError("GitHub数据发生并发修改，请刷新页面后重试。")
        if not response.ok:
            raise StorageError(
                f"GitHub写入失败：HTTP {response.status_code}，{response.text[:300]}"
            )
