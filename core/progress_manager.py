"""
进度管理模块 - 支持断点续传
将翻译进度保存到文件，支持从中断处继续
"""
import os
import json
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class PageProgress:
    """单页翻译进度"""
    page_num: int
    total_blocks: int
    translated_blocks: int
    completed: bool
    blocks_data: Dict[int, str]  # block_idx -> translated_text


class ProgressManager:
    """进度管理器 - 保存和恢复翻译进度"""

    def __init__(self, task_id: str, data_dir: str):
        self.task_id = task_id
        self.data_dir = data_dir
        self.progress_file = os.path.join(data_dir, f"{task_id}_progress.json")
        self.lock = threading.Lock()

        # 进度数据
        self.total_pages = 0
        self.current_page = 0
        self.pages: Dict[int, PageProgress] = {}
        self.status = "pending"
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()

        # 确保目录存在
        os.makedirs(data_dir, exist_ok=True)

    def save(self):
        """保存进度到文件"""
        with self.lock:
            self.updated_at = datetime.now().isoformat()
            data = {
                "task_id": self.task_id,
                "total_pages": self.total_pages,
                "current_page": self.current_page,
                "status": self.status,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "pages": {
                    str(k): {
                        "page_num": v.page_num,
                        "total_blocks": v.total_blocks,
                        "translated_blocks": v.translated_blocks,
                        "completed": v.completed,
                        "blocks_data": v.blocks_data
                    }
                    for k, v in self.pages.items()
                }
            }
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self) -> bool:
        """从文件加载进度，返回是否存在"""
        if not os.path.exists(self.progress_file):
            return False

        try:
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.total_pages = data.get("total_pages", 0)
            self.current_page = data.get("current_page", 0)
            self.status = data.get("status", "pending")
            self.created_at = data.get("created_at", "")
            self.updated_at = data.get("updated_at", "")

            # 加载页面进度
            self.pages = {}
            for k, v in data.get("pages", {}).items():
                self.pages[int(k)] = PageProgress(
                    page_num=v["page_num"],
                    total_blocks=v["total_blocks"],
                    translated_blocks=v["translated_blocks"],
                    completed=v["completed"],
                    blocks_data={int(bk): bv for bk, bv in v["blocks_data"].items()}
                )
            return True
        except Exception as e:
            print(f"加载进度失败: {e}")
            return False

    def init_page(self, page_num: int, total_blocks: int):
        """初始化页面进度"""
        with self.lock:
            self.pages[page_num] = PageProgress(
                page_num=page_num,
                total_blocks=total_blocks,
                translated_blocks=0,
                completed=False,
                blocks_data={}
            )

    def update_block(self, page_num: int, block_idx: int, translated_text: str):
        """更新单个块的翻译结果"""
        with self.lock:
            if page_num in self.pages:
                page = self.pages[page_num]
                page.blocks_data[block_idx] = translated_text
                page.translated_blocks = len(page.blocks_data)

    def complete_page(self, page_num: int):
        """标记页面完成"""
        with self.lock:
            if page_num in self.pages:
                self.pages[page_num].completed = True
                self.current_page = page_num + 1

    def get_page_translations(self, page_num: int) -> Dict[int, str]:
        """获取页面的翻译结果"""
        with self.lock:
            if page_num in self.pages:
                return self.pages[page_num].blocks_data.copy()
            return {}

    def is_page_completed(self, page_num: int) -> bool:
        """检查页面是否已完成"""
        with self.lock:
            if page_num in self.pages:
                return self.pages[page_num].completed
            return False

    def get_overall_progress(self) -> Dict[str, Any]:
        """获取总体进度"""
        with self.lock:
            total_blocks = sum(p.total_blocks for p in self.pages.values())
            translated_blocks = sum(p.translated_blocks for p in self.pages.values())
            completed_pages = sum(1 for p in self.pages.values() if p.completed)

            return {
                "total_pages": self.total_pages,
                "completed_pages": completed_pages,
                "current_page": self.current_page,
                "total_blocks": total_blocks,
                "translated_blocks": translated_blocks,
                "status": self.status,
                "percent": (translated_blocks / total_blocks * 100) if total_blocks > 0 else 0
            }

    def set_status(self, status: str):
        """设置状态"""
        with self.lock:
            self.status = status

    def clear(self):
        """清除进度文件"""
        if os.path.exists(self.progress_file):
            os.remove(self.progress_file)
        self.pages = {}
        self.current_page = 0
        self.status = "pending"
