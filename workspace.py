"""Research Workspace storage and export, version 1.0.4."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import shutil
import stat
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

VERSION = "1.0.4"
SCHEMA = 1
ALLOWED_OPEN = {".html", ".htm", ".doc", ".docx", ".xls", ".xlsx", ".pdf",
                ".png", ".jpg", ".jpeg", ".gif", ".txt", ".md", ".ppt", ".pptx", ".csv"}
def uid():
    return str(uuid.uuid4())

def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")

def clean_name(name):
    value = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name).strip(" .")[:70]
    if not value or value.split(".")[0].upper() in {"CON","PRN","AUX","NUL",*[f"COM{i}" for i in range(1,10)],*[f"LPT{i}" for i in range(1,10)]}:
        value = "_" + (value or "未命名")
    return value

def is_link(p):
    s = p.lstat()
    return stat.S_ISLNK(s.st_mode) or bool(getattr(s, "st_file_attributes", 0) & 0x400)

def contained(root, relative, exists=False):
    """Resolve a workspace-relative path, rejecting traversal and every reparse point."""
    raw = str(relative).replace("\\", "/")
    parts = PurePosixPath(raw).parts
    if not parts or raw.startswith("/") or any(x in {"..", "."} or ":" in x for x in parts):
        raise ValueError("路径必须是安全的相对路径")
    base = Path(root).resolve(strict=True)
    current = base
    for part in parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if is_link(current):
                raise ValueError("归档目录包含符号链接或 Windows 重解析点")
    result = current.resolve(strict=exists)
    if not result.is_relative_to(base) or result == base:
        raise ValueError("文件路径超出工作区")
    return result

def safe_files(root):
    root = Path(root)
    if is_link(root):
        raise ValueError("文件源不能是符号链接或重解析点")
    if root.is_file():
        return [root]
    result = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(directory) / name
            if is_link(p):
                raise ValueError("目录内存在符号链接或重解析点：" + str(p))
        result.extend(Path(directory) / name for name in sorted(files))
    return sorted(result)

def project_path(data, project_id):
    parts, seen = [], set()
    while project_id:
        if project_id in seen:
            raise ValueError("项目层级形成循环")
        seen.add(project_id)
        p = data["projects"][project_id]
        parts.append(p["name"])
        project_id = p["parentId"]
    return list(reversed(parts))

def children(data, node_id):
    return sorted((n["id"] for n in data["nodes"].values() if n["parentId"] == node_id),
                  key=lambda x: (data["nodes"][x]["sortOrder"], x))

def branch(data, node_id):
    result, pending = [], [node_id]
    while pending:
        item = pending.pop()
        result.append(item)
        pending.extend(reversed(children(data, item)))
    return result

def ordered_nodes(data, map_id):
    return branch(data, data["mindmaps"][map_id]["rootNodeId"])

def node_path(data, node_id):
    parts = []
    while node_id:
        n = data["nodes"][node_id]
        parts.append(n["title"])
        node_id = n["parentId"]
    return list(reversed(parts))

def new_workspace(name):
    return {"id": uid(), "name": name, "version": VERSION, "schema": SCHEMA,
            "revision": 0, "preferences": {"sidebarWidth": 260, "lastMindmap": None, "theme": "ocean", "colorfulBranches": True, "taperLines": True},
            "projects": {}, "mindmaps": {}, "nodes": {}, "attachments": {},
            "basket": []}

def validate(data):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("工作区格式或版本不受支持")
    uuid.UUID(data["id"])
    for table in ("projects", "mindmaps", "nodes", "attachments"):
        if not isinstance(data[table], dict):
            raise ValueError("工作区表结构错误：" + table)
        for key, item in data[table].items():
            uuid.UUID(key)
            if item["id"] != key:
                raise ValueError("对象 ID 不一致")
    for p in data["projects"].values():
        if p["parentId"] and p["parentId"] not in data["projects"]:
            raise ValueError("项目父级不存在")
        project_path(data, p["id"])
    for m in data["mindmaps"].values():
        if m["projectId"] not in data["projects"] or m["rootNodeId"] not in data["nodes"]:
            raise ValueError("导图引用不完整")
        root = data["nodes"][m["rootNodeId"]]
        if root["mindmapId"] != m["id"] or root["parentId"] is not None:
            raise ValueError("导图根节点错误")
        actual = {n["id"] for n in data["nodes"].values() if n["mindmapId"] == m["id"]}
        # ponytail: iterative tree checks also handle deeply nested outlines.
        visited, pending = set(), [m["rootNodeId"]]
        while pending:
            k = pending.pop()
            if k in visited:
                raise ValueError("节点层级形成循环")
            visited.add(k)
            pending.extend(children(data, k))
        if visited != actual:
            raise ValueError("导图含孤立节点或循环")
    for n in data["nodes"].values():
        if n["mindmapId"] not in data["mindmaps"]:
            raise ValueError("节点所属导图不存在")
        if n["parentId"]:
            parent = data["nodes"].get(n["parentId"])
            if not parent or parent["mindmapId"] != n["mindmapId"]:
                raise ValueError("节点父级错误")
        if any(a not in data["attachments"] for a in n["attachmentIds"]):
            raise ValueError("附件引用不存在")
        import re
        if any(not re.fullmatch(r"#[0-9a-fA-F]{6}", n["style"][k]) for k in ("background","foreground")):
            raise ValueError("节点颜色格式错误")
        if not isinstance(n["bodyRichText"]["text"], str):
            raise ValueError("正文格式错误")
        for h in n["bodyRichText"].get("highlights", []):
            if not 0 <= h["start"] < h["end"] <= len(n["bodyRichText"]["text"]):
                raise ValueError("高亮片段范围错误")
    for a in data["attachments"].values():
        parts = PurePosixPath(a["relativePath"]).parts
        if (len(parts) != 5 or parts[0] != "projects" or parts[2] != "attachments"
                or parts[1] != a["ownerProjectId"] or parts[3] != a["id"]
                or ".." in parts or ":" in a["relativePath"] or "\\" in a["relativePath"]):
            raise ValueError("附件路径不安全")
        uuid.UUID(a["ownerProjectId"])
        if a.get("entry"):
            e = PurePosixPath(a["entry"]).parts
            if not e or a["entry"].startswith("/") or ".." in e or ":" in a["entry"] or "\\" in a["entry"]:
                raise ValueError("HTML 入口路径不安全")
    for b in data["basket"]:
        table = {"node": "nodes", "attachment": "attachments"}.get(b["kind"])
        if not table or b["id"] not in data[table]:
            raise ValueError("选择篮引用失效")
    return data

def atomic_json(path, data):
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    temporary = path.with_name(path.name + "." + uid() + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        validate(json.loads(temporary.read_text(encoding="utf-8")))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

class Workspace:
    def __init__(self, root, create=True):
        self.root = Path(root).resolve()
        if self.root.exists() and is_link(Path(root)):
            raise ValueError("工作区不能是重解析点")
        self.root.mkdir(parents=True, exist_ok=True)
        self.metadata = contained(self.root, "workspace.json")
        self.lock = contained(self.root, ".workspace.lock")
        self.lock_owned = False
        self.recovered_from = None
        self.undo_stack, self.redo_stack = [], []
        self._acquire_lock()
        try:
            if self.metadata.exists():
                try:
                    self.data = validate(json.loads(self.metadata.read_text(encoding="utf-8")))
                except (ValueError, KeyError, TypeError, OSError):
                    self.data = self._recover()
            elif create:
                # Existing backup-only folders require recovery instead of silent initialization.
                snapshots = self.root / "snapshots"
                if snapshots.exists() and list(snapshots.glob("*.json")):
                    self.data = self._recover()
                else:
                    self.data = new_workspace(self.root.name)
            else:
                raise ValueError("工作区元数据不存在")
            self.revision = self.data.get("revision", 0)
            if not self.metadata.exists():
                self.save()
        except Exception:
            self.close()
            raise

    def _acquire_lock(self):
        import ctypes
        for attempt in range(2):
            try:
                fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    json.dump({"pid": os.getpid(), "created": stamp()}, f)
                self.lock_owned = True
                return
            except FileExistsError:
                try:
                    owner = json.loads(self.lock.read_text())["pid"]
                except Exception:
                    raise ValueError("工作区锁文件格式异常，请确认其他实例关闭后检查 .workspace.lock")
                if os.name == "nt":
                    kernel = ctypes.windll.kernel32
                    from ctypes import wintypes
                    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
                    kernel.OpenProcess.restype=wintypes.HANDLE
                    kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
                    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
                    handle=kernel.OpenProcess(0x1000,False,int(owner))
                    if handle:
                        try:
                            code=wintypes.DWORD()
                            alive=not kernel.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
                        finally:
                            kernel.CloseHandle(handle)
                    else:
                        alive=kernel.GetLastError()!=87
                else:
                    try:
                        os.kill(owner, 0)
                        alive = True
                    except ProcessLookupError:
                        alive = False
                if alive:
                    raise ValueError("此工作区已由另一个程序实例打开")
                self.lock.unlink()
        raise ValueError("无法取得工作区锁")

    def close(self):
        if self.lock_owned:
            self.lock.unlink(missing_ok=True)
            self.lock_owned = False

    def _recover(self):
        folder = contained(self.root, "snapshots")
        for p in sorted(folder.glob("*.json"), reverse=True):
            try:
                if is_link(p):
                    continue
                value = validate(json.loads(p.read_text(encoding="utf-8")))
                self.recovered_from = p.name
                return value
            except (ValueError, TypeError, KeyError, OSError):
                pass
        raise ValueError("元数据损坏，且未找到有效快照；请从工作区 ZIP 备份恢复")

    def checkpoint(self):
        self.undo_stack.append(copy.deepcopy(self.data))
        self.undo_stack = self.undo_stack[-40:]
        self.redo_stack.clear()

    def undo(self, redo=False):
        source, destination = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if not source:
            return False
        destination.append(copy.deepcopy(self.data))
        restored = source.pop()
        restored["attachments"].update(self.data["attachments"])
        self.data = restored
        return True

    def save(self):
        self.metadata = contained(self.root,"workspace.json")
        validate(self.data)
        if self.metadata.exists() and not self.recovered_from:
            old = json.loads(self.metadata.read_text(encoding="utf-8"))
            if old.get("revision", 0) != self.revision:
                raise ValueError("元数据已由外部程序修改，请重新打开工作区")
        folder = contained(self.root, "snapshots")
        folder.mkdir(exist_ok=True)
        if self.metadata.exists() and not self.recovered_from:
            old = validate(json.loads(self.metadata.read_text(encoding="utf-8")))
            backup = folder / (str(time.time_ns()) + ".json")
            atomic_json(backup, old)
        elif self.metadata.exists() and self.recovered_from:
            damaged = contained(self.root, "recovery")
            damaged.mkdir(exist_ok=True)
            shutil.copy2(self.metadata, damaged / ("workspace_" + str(time.time_ns()) + ".json"))
        self.data["revision"] = self.revision + 1
        self.data["version"] = VERSION
        atomic_json(self.metadata, self.data)
        self.revision += 1
        self.recovered_from = None
        for p in sorted(folder.glob("*.json"), reverse=True)[20:]:
            p.unlink()

    def add_project(self, name, parent=None):
        if parent and parent not in self.data["projects"]:
            raise ValueError("父项目不存在")
        i = uid()
        self.data["projects"][i] = {"id": i, "name": name.strip() or "新项目",
            "parentId": parent, "sortOrder": len(self.data["projects"])}
        return i

    def add_map(self, project, name, starter=False):
        if project not in self.data["projects"]:
            raise ValueError("项目不存在")
        m, n = uid(), uid()
        self.data["mindmaps"][m] = {"id": m, "name": name, "projectId": project,
            "rootNodeId": n, "viewState": {"zoom": 1.0}}
        self.data["nodes"][n] = self._node(n, m, None, name)
        if starter:
            parent = n
            for title in ("子节点","子子节点","子子子节点"):
                parent = self.add_node(parent,title)
        return m

    def _node(self, i, m, parent, title):
        return {"id": i, "mindmapId": m, "parentId": parent,
            "sortOrder": len(self.data["nodes"]), "title": title,
            "bodyRichText": {"text": "", "highlights": []}, "notes": "",
            "style": {"background": "#e8efff", "foreground": "#172947"},
            "collapsed": False, "attachmentIds": []}

    def add_node(self, parent, title="新节点", sibling=False):
        n = self.data["nodes"][parent]
        if sibling and n["parentId"]:
            parent = n["parentId"]
        i = uid()
        self.data["nodes"][i] = self._node(i, n["mindmapId"], parent, title)
        return i

    def move_node(self, i, parent):
        n, p = self.data["nodes"][i], self.data["nodes"][parent]
        if n["parentId"] is None:
            raise ValueError("根节点保持在导图根部")
        if n["mindmapId"] != p["mindmapId"] or parent in branch(self.data, i):
            raise ValueError("请选择同一导图内分支外的父节点")
        n["parentId"] = parent
        n["sortOrder"] = max((x["sortOrder"] for x in self.data["nodes"].values()), default=0) + 1

    def move_project(self, i, parent):
        if parent and parent == i:
            raise ValueError("项目不能移入自身")
        p = parent
        while p:
            if p == i:
                raise ValueError("项目不能移入自己的子项目")
            p = self.data["projects"][p]["parentId"]
        self.data["projects"][i]["parentId"] = parent

    def remove_nodes(self, ids):
        remove = set()
        for i in ids:
            if self.data["nodes"][i]["parentId"] is None:
                raise ValueError("根节点请通过删除导图处理")
            remove.update(branch(self.data, i))
        for i in remove:
            del self.data["nodes"][i]
        self.prune_basket()

    def remove_map(self, i):
        for n in ordered_nodes(self.data, i):
            del self.data["nodes"][n]
        del self.data["mindmaps"][i]
        self.prune_basket()

    def remove_project(self, i):
        ids, pending = set(), [i]
        while pending:
            p = pending.pop()
            ids.add(p)
            pending.extend(x["id"] for x in self.data["projects"].values() if x["parentId"] == p)
        for m in list(self.data["mindmaps"].values()):
            if m["projectId"] in ids:
                self.remove_map(m["id"])
        for p in ids:
            del self.data["projects"][p]
        self.prune_basket()

    def prune_basket(self):
        self.data["basket"] = [b for b in self.data["basket"] if b["id"] in
            self.data["nodes" if b["kind"] == "node" else "attachments"]]

    def basket_add(self, kind, ids):
        for i in ids:
            entry = {"kind": kind, "id": i}
            if entry not in self.data["basket"]:
                self.data["basket"].append(entry)

    def import_attachment(self, node, source, entry=None):
        source = Path(source)
        files = safe_files(source)
        if not source.is_file() and not source.is_dir():
            raise ValueError("请选择普通文件或目录")
        is_folder = source.is_dir()
        if is_folder and self.root.is_relative_to(source.resolve()):
            raise ValueError("导入目录不能包含当前工作区")
        if entry:
            entry = contained(source, entry, exists=True)
            if entry not in files or entry.suffix.lower() not in {".html", ".htm"}:
                raise ValueError("入口必须是该目录中的 HTML 文件")
        attachment = uid()
        project = self.data["mindmaps"][self.data["nodes"][node]["mindmapId"]]["projectId"]
        rel = f"projects/{project}/attachments/{attachment}"
        directory = contained(self.root, rel)
        directory.mkdir(parents=True, exist_ok=False)
        try:
            target = directory / source.name
            if is_folder:
                target.mkdir()
                for d, dirs, _ in os.walk(source):
                    for name in dirs:
                        (target / (Path(d) / name).relative_to(source)).mkdir(parents=True, exist_ok=True)
                for p in files:
                    shutil.copy2(p, target / p.relative_to(source))
            else:
                shutil.copy2(source, target)
            relative = rel + "/" + source.name
            entry_rel = str(entry.relative_to(source)).replace("\\", "/") if entry else None
            record = {"id": attachment, "ownerProjectId": project, "originalName": source.name,
                "relativePath": relative, "entry": entry_rel, "type": "folder" if is_folder else source.suffix.lower(),
                "size": sum(p.stat().st_size for p in files), "importedAt": stamp(),
                "modifiedAt": max((p.stat().st_mtime for p in files), default=time.time())}
            self.data["attachments"][attachment] = record
            self.data["nodes"][node]["attachmentIds"].append(attachment)
            return attachment
        except Exception:
            shutil.rmtree(directory)
            raise

    def attachment_path(self, i, for_open=False):
        a = self.data["attachments"][i]
        p = contained(self.root, a["relativePath"], exists=True)
        if for_open and a.get("entry"):
            p = contained(p, a["entry"], exists=True)
        return p

    def refresh_attachment(self, i):
        p = self.attachment_path(i)
        files = safe_files(p)
        a = self.data["attachments"][i]
        a["size"] = sum(x.stat().st_size for x in files)
        a["modifiedAt"] = max((x.stat().st_mtime for x in files), default=p.stat().st_mtime)
        return a

    def delete_attachment(self, i):
        if any(i in n["attachmentIds"] for n in self.data["nodes"].values()):
            raise ValueError("附件仍被节点引用，请先解除全部关联")
        p = self.attachment_path(i)
        bundle = p.parent
        if bundle.name != i:
            raise ValueError("附件目录结构异常")
        safe_files(bundle)
        shutil.rmtree(bundle)
        del self.data["attachments"][i]
        self.data["basket"] = [b for b in self.data["basket"] if b["id"] != i]
        # Physical deletion cannot be undone; old history would restore dangling references.
        self.undo_stack.clear()
        self.redo_stack.clear()

    def search(self, query):
        q, result = query.casefold(), []
        if not q:
            return result
        for p in self.data["projects"].values():
            if q in p["name"].casefold():
                result.append({"kind": "project", "id": p["id"], "text": p["name"],
                    "location": " / ".join(project_path(self.data, p["id"]))})
        for m in self.data["mindmaps"].values():
            location = " / ".join(project_path(self.data, m["projectId"]) + [m["name"]])
            if q in m["name"].casefold():
                result.append({"kind": "map", "id": m["id"], "text": m["name"], "location": location})
        for n in self.data["nodes"].values():
            values = [n["title"], n["bodyRichText"]["text"], n["notes"]]
            values.extend(self.data["attachments"][a]["originalName"] for a in n["attachmentIds"])
            matching = next((v for v in values if q in v.casefold()), None)
            if matching is not None:
                m = self.data["mindmaps"][n["mindmapId"]]
                at = matching.casefold().find(q)
                result.append({"kind": "node", "id": n["id"], "text": matching[max(0,at-20):at+100],
                    "location": " / ".join(project_path(self.data,m["projectId"])+[m["name"]]+node_path(self.data,n["id"]))})
        for a in self.data["attachments"].values():
            if q in a["originalName"].casefold() and not any(a["id"] in n["attachmentIds"] for n in self.data["nodes"].values()):
                owner = a["ownerProjectId"]
                result.append({"kind":"attachment","id":a["id"],"text":a["originalName"],
                    "location":" / ".join(project_path(self.data,owner)) if owner in self.data["projects"] else "归档附件"})
        return result

    def export_plan(self, refs, descendants=True):
        node_ids, direct = set(), set()
        for r in refs:
            if r["kind"] == "node" and r["id"] in self.data["nodes"]:
                node_ids.update(branch(self.data, r["id"]) if descendants else [r["id"]])
            elif r["kind"] == "attachment" and r["id"] in self.data["attachments"]:
                direct.add(r["id"])
        nodes = [n for m in self.data["mindmaps"] for n in ordered_nodes(self.data,m) if n in node_ids]
        references = {}
        for n in nodes:
            for a in self.data["nodes"][n]["attachmentIds"]:
                references.setdefault(a, []).append(n)
        for a in direct:
            references.setdefault(a, [])
        entries = []
        for a, sources in references.items():
            record = self.data["attachments"][a]
            if sources:
                node = self.data["nodes"][sources[0]]
                m = self.data["mindmaps"][node["mindmapId"]]
                pid = m["projectId"]
                hierarchy = project_path(self.data, pid) + [m["name"]] + node_path(self.data, node["id"])
            else:
                pid = record["ownerProjectId"]
                hierarchy = project_path(self.data,pid) if pid in self.data["projects"] else ["归档附件"]
            # UUID directories make collision handling stable across renames and duplicate names.
            short = [hierarchy[0][:28], hierarchy[-1][:28]] if len(hierarchy) > 1 else [hierarchy[0][:28]]
            rel = "/".join(clean_name(x) for x in short) + "/" + a + "/" + record["originalName"]
            entries.append({"id": a, "path": rel, "nodeIds": sources,
                            "originalName": record["originalName"], "entry": record.get("entry")})
        return {"nodes": nodes, "attachments": entries,
                "duplicates": sum(len(self.data["nodes"][n]["attachmentIds"]) for n in nodes)+len(direct)-len(entries)}


    def export(self, plan, parent, zip_mode=False, ai=True, include_text=True):
        parent = Path(parent).resolve(strict=True)
        if parent.is_relative_to(self.root):
            raise ValueError("请将导出目标设在工作区以外")
        destination = parent / ("Research_Export_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uid()[:8])
        destination.mkdir(exist_ok=False)
        stats = {"success": 0, "failed": 0, "skipped": plan["duplicates"], "errors": [], "files": []}
        mappings = []
        try:
            for entry in plan["attachments"]:
                mapping = dict(entry)
                record = self.data["attachments"][entry["id"]]
                owner = record["ownerProjectId"]
                mapping["ownerProjectId"] = owner
                mapping["ownerProjectPath"] = project_path(self.data,owner) if owner in self.data["projects"] else []
                mapping["sourceNodes"] = []
                for n in self.data["nodes"].values():
                    if entry["id"] in n["attachmentIds"]:
                        m = self.data["mindmaps"][n["mindmapId"]]
                        mapping["sourceNodes"].append({"id":n["id"],"projectId":m["projectId"],
                            "projectPath":project_path(self.data,m["projectId"]),
                            "mindmapId":m["id"],"mindmapName":m["name"],"nodePath":node_path(self.data,n["id"])})
                mapping["files"], mapping["warnings"] = [], []
                mappings.append(mapping)
                try:
                    source = self.attachment_path(entry["id"])
                    original_files = safe_files(source)
                    target = contained(destination, entry["path"])
                    if source.is_dir():
                        target.mkdir(parents=True, exist_ok=False)
                        for d, dirs, _ in os.walk(source):
                            for name in dirs:
                                (target / (Path(d) / name).relative_to(source)).mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                    for f in original_files:
                        out = target / f.relative_to(source) if source.is_dir() else target
                        try:
                            shutil.copy2(f, out)
                            source_hash = file_hash(f)
                            target_hash = file_hash(out)
                            if source_hash != target_hash:
                                raise ValueError("复制后字节校验失败，源文件可能正在修改")
                            rel = out.relative_to(destination).as_posix()
                            mapping["files"].append({"path": rel, "sha256": target_hash, "size": out.stat().st_size})
                            stats["files"].append(rel)
                            stats["success"] += 1
                            if f.suffix.lower() in {".html", ".htm"}:
                                mapping["warnings"].extend(html_warnings(f, source if source.is_dir() else f.parent,
                                                                         folder_import=source.is_dir()))
                        except Exception as e:
                            out.unlink(missing_ok=True)
                            stats["failed"] += 1
                            reason = entry["originalName"] + "/" + f.name + "：" + str(e)
                            stats["errors"].append(reason)
                            mapping["warnings"].append(reason)
                    if not original_files and not source.is_dir():
                        raise ValueError("附件不可读取")
                except Exception as e:
                    stats["failed"] += 1
                    stats["errors"].append(entry["originalName"] + "：" + str(e))
                    mapping["warnings"].append(str(e))
            selected = []
            for i in plan["nodes"]:
                n = self.data["nodes"][i]
                m = self.data["mindmaps"][n["mindmapId"]]
                selected.append({"id": i, "parentId": n["parentId"], "projectId": m["projectId"],
                    "projectPath": project_path(self.data,m["projectId"]), "mindmapId": m["id"],
                    "mindmapName": m["name"], "nodePath": node_path(self.data,i), "title": n["title"],
                    "bodyRichText": n["bodyRichText"] if include_text else {"text":"","highlights":[]},
                    "notes": n["notes"] if include_text else "", "style": n["style"],
                    "attachmentIds": n["attachmentIds"]})
            if ai:
                manifest = {"version": VERSION, "exportedAt": stamp(), "workspaceId": self.data["id"],
                    "contentIncluded": include_text, "nodes": selected, "attachments": mappings, "result": stats}
                (destination / "manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
                (destination / "README.md").write_text(
                    "# Research Workspace 资料包\n\n"
                    "manifest.json 记录来源、节点层级、附件相对路径、字节校验值和导出结果。\n"
                    "附件目录中的文件保持原始格式；HTML 文件夹保留相对资源结构。\n"
                    "outline.md 按所选节点的原始层级整理文字。文字来自原始节点。\n"
                    "请同时查看清单中的 warnings 和 result.errors；互联网资源需要联网访问。\n",
                    encoding="utf-8")
            if include_text or ai:
                (destination / "outline.md").write_text(make_outline(selected, include_text),encoding="utf-8")
            # A partial export always carries a durable, readable failure report.
            if stats["failed"]:
                (destination / "export_result.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8")
            output = destination
            if zip_mode:
                output = destination.with_suffix(".zip")
                try:
                    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
                        for f in safe_files(destination):
                            archive.write(f, f.relative_to(destination).as_posix())
                    with zipfile.ZipFile(output) as archive:
                        if archive.testzip():
                            raise ValueError("ZIP 校验失败")
                except Exception:
                    output.unlink(missing_ok=True)
                    raise
                shutil.rmtree(destination)
            stats["output"] = str(output)
            return stats
        except Exception:
            # Keep completed copies on failure so the user can recover useful work.
            raise

    def export_project_package(self, refs, output):
        """Package selected project subtrees and maps with their referenced files."""
        data = copy.deepcopy(self.data)
        projects, maps = set(), set()
        for ref in refs:
            kind, item = ref.split(":", 1)
            if kind == "p" and item in data["projects"]:
                pending = [item]
                while pending:
                    project = pending.pop()
                    if project in projects: continue
                    projects.add(project)
                    pending.extend(p["id"] for p in data["projects"].values() if p["parentId"] == project)
            elif kind == "m" and item in data["mindmaps"]:
                maps.add(item)
        maps.update(m["id"] for m in data["mindmaps"].values() if m["projectId"] in projects)
        if not projects and not maps:
            raise ValueError("请在左侧选择项目、文件夹或思维导图")
        selected_projects=set(projects)
        # Preserve ancestor folders as containers for selected maps and subtrees.
        for project in list(projects) + [data["mindmaps"][m]["projectId"] for m in maps]:
            while project:
                projects.add(project)
                project = data["projects"][project]["parentId"]
        nodes = {n["id"] for n in data["nodes"].values() if n["mindmapId"] in maps}
        attachments = {a for n in nodes for a in data["nodes"][n]["attachmentIds"]}
        attachments.update(a["id"] for a in data["attachments"].values() if a["ownerProjectId"] in selected_projects)
        for table, selected in (("projects", projects), ("mindmaps", maps),
                                ("nodes", nodes), ("attachments", attachments)):
            data[table] = {i: record for i, record in data[table].items() if i in selected}
        data["id"], data["version"], data["revision"], data["basket"] = uid(), VERSION, 0, []
        if data["preferences"].get("lastMindmap") not in maps:
            data["preferences"]["lastMindmap"] = next(iter(data["mindmaps"]), None)
        validate(data)
        output = Path(output).absolute()
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise ValueError("项目包文件已存在，请选择新文件名")
        temporary = output.with_name(output.name + "." + uid() + ".tmp")
        try:
            with zipfile.ZipFile(temporary, "x", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("project_package.json", json.dumps({
                    "format": "ResearchWorkspaceProject", "formatVersion": 1,
                    "appVersion": VERSION}, ensure_ascii=False))
                archive.writestr("workspace.json", json.dumps(data, ensure_ascii=False, indent=2))
                for record in data["attachments"].values():
                    source = contained(self.root, record["relativePath"], exists=True)
                    files = safe_files(source)
                    if source.is_dir():
                        for directory, _, _ in os.walk(source):
                            archive.write(directory, Path(directory).relative_to(self.root).as_posix() + "/")
                    for file in files:
                        archive.write(file, file.relative_to(self.root).as_posix())
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip():
                    raise ValueError("项目包校验失败")
            with output.open("xb"): pass
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        return output

    def backup(self, output):
        self.save()
        output = Path(output).resolve()
        if output.is_relative_to(self.root):
            raise ValueError("备份目标必须位于工作区以外")
        if output.exists():
            raise ValueError("备份目标已存在，请选择新文件名")
        files = safe_files(self.root)
        temp = output.with_name(output.name + "." + uid() + ".tmp")
        try:
            with zipfile.ZipFile(temp,"x",zipfile.ZIP_DEFLATED) as z:
                for p in files:
                    if p == self.lock or p.name.endswith(".tmp"):
                        continue
                    z.write(p,p.relative_to(self.root).as_posix())
                for directory, dirs, _ in os.walk(self.root):
                    for name in dirs:
                        d = Path(directory) / name
                        z.write(d,d.relative_to(self.root).as_posix()+"/")
            with zipfile.ZipFile(temp) as z:
                if z.testzip():
                    raise ValueError("备份 ZIP 完整性校验失败")
            # Exclusive creation reserves the user-selected filename.
            with output.open("xb"):
                pass
            os.replace(temp,output)
        finally:
            temp.unlink(missing_ok=True)
        return output

def file_hash(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()

def make_outline(nodes, include_text=True):
    lines, previous_map = ["# 科研资料大纲", ""], None
    for n in nodes:
        if n["mindmapId"] != previous_map:
            lines += ["## " + " / ".join(n["projectPath"] + [n["mindmapName"]]), ""]
            previous_map = n["mindmapId"]
        indent = "  " * (len(n["nodePath"]) - 1)
        lines.append(indent + "- " + n["title"].replace("\n"," "))
        if include_text:
            for label, text in [("正文",n["bodyRichText"]["text"]),("备注",n["notes"])]:
                if text:
                    lines.append(indent + "  " + label + "：")
                    lines.extend(indent + "    " + row for row in text.splitlines())
        lines.append("")
    return "\n".join(lines)

def html_warnings(file, base, folder_import):
    import re
    from urllib.parse import unquote, urlsplit
    value = Path(file).read_text(encoding="utf-8",errors="replace")
    result = []
    for link in re.findall(r"(?:src|href)\s*=\s*[\"']([^\"']+)",value,re.I):
        if link.startswith(("http://","https://","//")):
            result.append("远端资源需要联网：" + link)
        elif link.startswith(("data:","#","mailto:","javascript:","tel:")):
            continue
        else:
            rel = unquote(urlsplit(link).path)
            p = (Path(file).parent / rel).resolve()
            if not p.is_relative_to(Path(base).resolve()) or not p.exists():
                result.append("未归档或无法访问的依赖：" + link)
            elif not folder_import and p != Path(file).resolve():
                result.append("单文件导入未包含依赖：" + link)
    return sorted(set(result))

def restore_backup(archive, destination):
    destination = Path(destination).absolute()
    if destination.exists():
        raise ValueError("恢复目标必须是新目录")
    with zipfile.ZipFile(archive) as z:
        names = set()
        total = 0
        for item in z.infolist():
            name = item.filename
            parts = PurePosixPath(name).parts
            if (not parts or name.startswith("/") or "\\" in name or any(x in {"..","."} or ":" in x for x in parts)
                or any(any(c in '<>:"|?*' or ord(c)<32 for c in x) or x.endswith((" ","."))
                    or x.split(".")[0].upper() in {"CON","PRN","AUX","NUL",*[f"COM{i}" for i in range(1,10)],*[f"LPT{i}" for i in range(1,10)]}
                    for x in parts) or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError("ZIP 含不安全路径、文件名或符号链接")
            normalized = name.rstrip("/").casefold()
            if normalized in names:
                raise ValueError("ZIP 含重复文件路径")
            names.add(normalized)
            total += item.file_size
            if total > 20 * 1024 ** 3 or item.file_size > max(1024**2, item.compress_size * 1000):
                raise ValueError("备份大小或压缩比超出安全限制")
        if len(z.infolist()) > 100000:
            raise ValueError("Archive entry limit exceeded")
        if "workspace.json" not in z.namelist():
            raise ValueError("ZIP 缺少 workspace.json")
        if z.getinfo("workspace.json").file_size > 64 * 1024 ** 2:
            raise ValueError("Metadata size limit exceeded")
        if Path(archive).suffix.lower() == ".rwp":
            if "project_package.json" not in z.namelist() or z.getinfo("project_package.json").file_size > 4096:
                raise ValueError("项目包标识缺失或异常")
            manifest = json.loads(z.read("project_package.json").decode("utf-8"))
            if manifest.get("format") != "ResearchWorkspaceProject" or manifest.get("formatVersion") != 1:
                raise ValueError("项目包格式不受支持")
        data = validate(json.loads(z.read("workspace.json").decode("utf-8")))
        for a in data["attachments"].values():
            prefix = a["relativePath"]
            matching = [n for n in z.namelist() if n == prefix or n.startswith(prefix + "/")]
            if not matching and prefix + "/" not in z.namelist():
                raise ValueError("备份缺失附件：" + a["originalName"])
            if a.get("entry") and prefix + "/" + a["entry"] not in z.namelist():
                raise ValueError("备份缺失 HTML 入口")
        if z.testzip():
            raise ValueError("ZIP 字节校验失败")
        destination.mkdir(parents=True,exist_ok=False)
        try:
            for item in z.infolist():
                if item.filename == ".workspace.lock":
                    continue
                p = contained(destination,item.filename)
                if item.is_dir():
                    p.mkdir(parents=True,exist_ok=True)
                else:
                    p.parent.mkdir(parents=True,exist_ok=True)
                    with z.open(item) as src, p.open("xb") as dst:
                        shutil.copyfileobj(src,dst)
            return destination
        except Exception:
            shutil.rmtree(destination)
            raise
