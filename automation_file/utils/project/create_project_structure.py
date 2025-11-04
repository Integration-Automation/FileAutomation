from os import getcwd
from pathlib import Path
from threading import Lock

from automation_file.utils.json.json_file import write_action_json
from automation_file.utils.logging.loggin_instance import file_automation_logger
from automation_file.utils.project.template.template_executor import (
    executor_template_1, executor_template_2, bad_executor_template_1
)
from automation_file.utils.project.template.template_keyword import (
    template_keyword_1, template_keyword_2, bad_template_1
)


def create_dir(dir_name: str) -> None:
    """
    建立資料夾 (若不存在則自動建立)
    Create a directory (auto-create if not exists)

    :param dir_name: 資料夾名稱或路徑
    :return: None
    """
    Path(dir_name).mkdir(parents=True, exist_ok=True)


def create_template(parent_name: str, project_path: str = None) -> None:
    """
    在專案目錄下建立 keyword JSON 與 executor Python 檔案
    Create keyword JSON files and executor Python files under project directory

    :param parent_name: 專案主資料夾名稱
    :param project_path: 專案路徑 (預設為當前工作目錄)
    """
    if project_path is None:
        project_path = getcwd()

    keyword_dir_path = Path(f"{project_path}/{parent_name}/keyword")
    executor_dir_path = Path(f"{project_path}/{parent_name}/executor")

    lock = Lock()

    # === 建立 keyword JSON 檔案 ===
    if keyword_dir_path.exists() and keyword_dir_path.is_dir():
        write_action_json(str(keyword_dir_path / "keyword1.json"), template_keyword_1)
        write_action_json(str(keyword_dir_path / "keyword2.json"), template_keyword_2)
        write_action_json(str(keyword_dir_path / "bad_keyword_1.json"), bad_template_1)

    # === 建立 executor Python 檔案 ===
    if executor_dir_path.exists() and executor_dir_path.is_dir():
        with lock:
            with open(executor_dir_path / "executor_one_file.py", "w+", encoding="utf-8") as file:
                file.write(
                    executor_template_1.replace(
                        "{temp}", str(keyword_dir_path / "keyword1.json")
                    )
                )
            with open(executor_dir_path / "executor_bad_file.py", "w+", encoding="utf-8") as file:
                file.write(
                    bad_executor_template_1.replace(
                        "{temp}", str(keyword_dir_path / "bad_keyword_1.json")
                    )
                )
            with open(executor_dir_path / "executor_folder.py", "w+", encoding="utf-8") as file:
                file.write(
                    executor_template_2.replace(
                        "{temp}", str(keyword_dir_path)
                    )
                )


def create_project_dir(project_path: str = None, parent_name: str = "FileAutomation") -> None:
    """
    建立專案目錄結構 (包含 keyword 與 executor 資料夾)，並生成範例檔案
    Create project directory structure (with keyword and executor folders) and generate template files

    :param project_path: 專案路徑 (預設為當前工作目錄)
    :param parent_name: 專案主資料夾名稱 (預設 "FileAutomation")
    """
    file_automation_logger.info(
        f"create_project_dir, project_path: {project_path}, parent_name: {parent_name}"
    )

    if project_path is None:
        project_path = getcwd()

    # 建立 keyword 與 executor 資料夾
    create_dir(f"{project_path}/{parent_name}/keyword")
    create_dir(f"{project_path}/{parent_name}/executor")

    # 建立範例檔案
    create_template(parent_name, project_path)