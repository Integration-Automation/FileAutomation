from importlib import import_module
from importlib.util import find_spec
from inspect import getmembers, isfunction, isbuiltin, isclass
from sys import stderr

from automation_file.utils.logging.loggin_instance import file_automation_logger


class PackageManager(object):
    """
    PackageManager 負責：
    - 檢查套件是否存在並載入
    - 將套件中的函式、內建函式、類別註冊到 executor 或 callback_executor
    """

    def __init__(self):
        # 已安裝套件快取，避免重複 import
        # Cache for installed packages
        self.installed_package_dict = {}
        self.executor = None
        self.callback_executor = None

    def check_package(self, package: str):
        """
        檢查並載入套件
        Check if a package exists and import it

        :param package: 套件名稱 (str)
        :return: 套件模組物件，若不存在則回傳 None
        """
        if self.installed_package_dict.get(package, None) is None:
            found_spec = find_spec(package)
            if found_spec is not None:
                try:
                    installed_package = import_module(found_spec.name)
                    self.installed_package_dict.update(
                        {found_spec.name: installed_package}
                    )
                except ModuleNotFoundError as error:
                    print(repr(error), file=stderr)
        return self.installed_package_dict.get(package, None)

    def add_package_to_executor(self, package):
        """
        將套件的成員加入 executor 的 event_dict
        Add package members to executor's event_dict
        """
        file_automation_logger.info(f"add_package_to_executor, package: {package}")
        self.add_package_to_target(package=package, target=self.executor)

    def add_package_to_callback_executor(self, package):
        """
        將套件的成員加入 callback_executor 的 event_dict
        Add package members to callback_executor's event_dict
        """
        file_automation_logger.info(f"add_package_to_callback_executor, package: {package}")
        self.add_package_to_target(package=package, target=self.callback_executor)

    def get_member(self, package, predicate, target):
        """
        取得套件成員並加入目標 event_dict
        Get members of a package and add them to target's event_dict

        :param package: 套件名稱
        :param predicate: 過濾條件 (isfunction, isbuiltin, isclass)
        :param target: 目標 executor/callback_executor
        """
        installed_package = self.check_package(package)
        if installed_package is not None and target is not None:
            for member in getmembers(installed_package, predicate):
                target.event_dict.update(
                    {f"{package}_{member[0]}": member[1]}
                )
        elif installed_package is None:
            print(repr(ModuleNotFoundError(f"Can't find package {package}")), file=stderr)
        else:
            print(f"Executor error {self.executor}", file=stderr)

    def add_package_to_target(self, package, target):
        """
        將套件的 function、builtin、class 成員加入指定 target
        Add functions, builtins, and classes from a package to target

        :param package: 套件名稱
        :param target: 目標 executor/callback_executor
        """
        try:
            self.get_member(package=package, predicate=isfunction, target=target)
            self.get_member(package=package, predicate=isbuiltin, target=target)
            self.get_member(package=package, predicate=isclass, target=target)
        except Exception as error:
            print(repr(error), file=stderr)


# 建立單例，供其他模組使用
package_manager = PackageManager()